"""Motor de animação via Google Veo (Vertex AI), image-to-video.

Contrato generate() plugável no _motor() do clipes.py (motor único do projeto).
Fluxo: keyframe em base64 -> predictLongRunning -> poll fetchPredictOperation -> mp4.
A operação (operation name) é devolvida ao chamador ANTES do poll (persistida no
roteiro.json como 'model::operation'), permitindo retomar sem pagar de novo.

Gera SEM áudio (b-roll silencioso) — a narração entra na montagem, igual fal/Wan.

Requer:
  - gcloud autenticado (gcloud auth login) — usado só para o access token.
  - VEO_PROJECT no ambiente (ou [video].veo_project no config.toml): id do projeto GCP.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import random
import shutil
import ssl
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

REGION = os.environ.get("VEO_REGION", "us-central1")

# Slugs -> modelos publicados no Vertex. Se o Google renomear, ajuste SÓ aqui.
MODEL_MAP = {
    "veo_lite": "veo-3.1-lite-generate-001",     # padrao da casa: metade do preco do fast
    "veo_fast": "veo-3.1-fast-generate-001",
    "veo_quality": "veo-3.1-generate-001",
}

_GCLOUD_DEFAULT = r"C:\Users\Leon\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"


def _ffmpeg() -> str:
    try:
        from workspace import carregar_config
        return (carregar_config().get("app", {}).get("ffmpeg") or "").strip() or "ffmpeg"
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def _keyframe_9x16_b64(img: Path) -> tuple[str, str]:
    """Corta o keyframe pro 9:16 centralizado antes de mandar ao Veo. Sem isso, quando o
    keyframe é 2:3 (1024x1536) o Veo preenche o 9:16 com TARJAS pretas. Se o corte falhar,
    manda a imagem original (best-effort)."""
    try:
        import tempfile
        tmp = Path(tempfile.gettempdir()) / f".veo916_{img.stem}.png"
        r = subprocess.run(
            [_ffmpeg(), "-y", "-i", str(img),
             "-vf", "crop='min(iw,ih*9/16)':ih", "-frames:v", "1", str(tmp)],
            capture_output=True, creationflags=_NO_WINDOW)
        if r.returncode == 0 and tmp.exists():
            data = base64.b64encode(tmp.read_bytes()).decode("ascii")
            tmp.unlink(missing_ok=True)
            return data, "image/png"
    except Exception:  # noqa: BLE001
        pass
    mime = mimetypes.guess_type(img.name)[0] or "image/png"
    return base64.b64encode(img.read_bytes()).decode("ascii"), mime


def _veo_dur(duration_s) -> int:
    """Veo image_to_video só aceita 4, 6 ou 8s. Arredonda pra CIMA (não corta a fala)."""
    d = int(duration_s or 4)
    for a in (4, 6, 8):
        if d <= a:
            return a
    return 8


def _gcloud() -> str:
    exe = os.environ.get("GCLOUD_PATH") or shutil.which("gcloud")
    if exe:
        return exe
    if Path(_GCLOUD_DEFAULT).exists():
        return _GCLOUD_DEFAULT
    # Mac: locais canônicos do SDK (instalador oficial no home; cask do brew em share/).
    for c in (Path.home() / "google-cloud-sdk" / "bin" / "gcloud",
              Path("/usr/local/share/google-cloud-sdk/bin/gcloud"),
              Path("/opt/homebrew/share/google-cloud-sdk/bin/gcloud"),
              Path("/opt/homebrew/bin/gcloud"), Path("/usr/local/bin/gcloud")):
        if c.exists():
            return str(c)
    raise RuntimeError("gcloud não encontrado. Instale o Google Cloud SDK e rode 'gcloud auth login'.")


def _sa_key_path() -> Path | None:
    """Chave de service account embutida — permite gerar vídeo SEM login interativo do
    Google (o instalador do Mac embute a chave). Procura, nesta ordem: env
    GOOGLE_APPLICATION_CREDENTIALS, a pasta gravável de config, o template embutido no
    app (BUNDLE_DIR/_default_config) e, em dev, ao lado do default_config do repo.
    Retorna None se nenhuma existir (aí cai no gcloud login normal — caso Windows)."""
    cands = []
    env = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if env:
        cands.append(Path(env))
    try:
        from workspace import CONFIG_DIR, BUNDLE_DIR
        cands.append(CONFIG_DIR / "veo_sa.json")
        cands.append(BUNDLE_DIR / "_default_config" / "veo_sa.json")
    except Exception:  # noqa: BLE001
        pass
    cands.append(Path(__file__).resolve().parent.parent
                 / "packaging" / "default_config" / "veo_sa.json")
    for c in cands:
        try:
            if c and c.exists() and c.stat().st_size > 0:
                return c
        except Exception:  # noqa: BLE001
            continue
    return None


def _project() -> str:
    p = (os.environ.get("VEO_PROJECT") or "").strip()
    if p:
        return p
    try:
        from workspace import carregar_config
        p = (carregar_config().get("video", {}).get("veo_project") or "").strip()
    except Exception:  # noqa: BLE001
        p = ""
    if not p:  # último fallback: o project_id da própria chave de serviço embutida.
        key = _sa_key_path()
        if key:
            try:
                p = (json.loads(key.read_text(encoding="utf-8")).get("project_id") or "").strip()
            except Exception:  # noqa: BLE001
                p = ""
    if not p:
        raise RuntimeError("VEO_PROJECT não configurado (.env) nem [video].veo_project no config.toml.")
    return p


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no Windows, não abre console do gcloud
_tok_cache = {"val": None, "exp": 0.0}
_tok_lock = threading.Lock()
_sa_ativada = [False]  # ativa a service account embutida no máx. 1x por processo


def _garantir_sa_ativa() -> None:
    """Se há chave de serviço embutida (instalação sem login do Google), garante que ELA
    é a conta ativa do gcloud antes de pedir o token. Sem isso, uma conta de usuário
    antiga ainda logada pegaria um token da IDENTIDADE errada (403 no projeto novo). Sem
    chave embutida (Windows/dev), não faz nada — usa o login normal do gcloud."""
    if _sa_ativada[0]:
        return
    _sa_ativada[0] = True  # tenta só uma vez, mesmo se falhar (não trava o poll)
    key = _sa_key_path()
    if not key:
        return
    try:
        subprocess.check_call(
            [_gcloud(), "auth", "activate-service-account", "--key-file", str(key)],
            creationflags=_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001 — se falhar, cai no que já estiver logado
        pass


def _token() -> str:
    """Access token do gcloud, cacheado ~45min. Sem cache seria 1 chamada a cada poll (8s),
    piscando um console do Windows toda vez. O lock evita que várias threads (lote de 6
    clipes) disparem `gcloud` em paralelo — só a primeira busca, as demais reusam o cache."""
    with _tok_lock:
        now = time.time()
        if _tok_cache["val"] and now < _tok_cache["exp"]:
            return _tok_cache["val"]
        _garantir_sa_ativa()
        val = subprocess.check_output([_gcloud(), "auth", "print-access-token"],
                                      text=True, creationflags=_NO_WINDOW).strip()
        _tok_cache["val"] = val
        _tok_cache["exp"] = now + 2700
        return val


def _base() -> str:
    proj = _project()
    return (f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{proj}"
            f"/locations/{REGION}/publishers/google/models")


_ctx_cache = []


def _ssl_ctx():
    """Contexto SSL com CAs válidas. No macOS (principalmente dentro do .app congelado) o
    ssl do Python não enxerga o Keychain do sistema e o verify falha com
    "unable to get local issuer certificate" — o certifi resolve. No Windows/Linux o
    contexto padrão já funciona; aqui o certifi só é usado se estiver instalado."""
    if _ctx_cache:
        return _ctx_cache[0]
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — sem certifi, usa o padrão do sistema
        ctx = ssl.create_default_context()
    _ctx_cache.append(ctx)
    return ctx


def _post(url: str, body: dict, token: str, timeout: int = 120) -> dict:
    """POST no Vertex. Em 401 (token expirado no meio de um lote longo) INVALIDA o cache
    de token e tenta UMA vez com um token novo. Sem isso, um lote de varias horas perde
    clipes ja pagos: foi o que derrubou o C2 inteiro e a ultima cena do C3 no lote
    Baba Baby de 24/08 (o cache dura 45min, mas o lote dura horas)."""
    for tentativa in (1, 2):
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:  # noqa: PERF203
            detalhe = e.read().decode(errors='replace')[:600]
            if e.code == 401 and tentativa == 1:
                with _tok_lock:                      # forca renovacao no proximo _token()
                    _tok_cache["val"], _tok_cache["exp"] = "", 0.0
                token = _token()
                continue
            raise RuntimeError(f"Vertex/Veo recusou ({e.code}): {detalhe}")
    raise RuntimeError("Vertex/Veo recusou (401) mesmo apos renovar o token.")


# Espaçamento entre submits: quando 6 clipes disparam juntos, bater no Vertex no MESMO
# instante é o que provoca o throttle (code 8 / high load). Serializa só o INSTANTE do
# submit (~0,8s entre um e outro); a parte longa (poll) segue concorrente. Reduz o pico.
_submit_gate = threading.Lock()
_ultimo_submit = [0.0]
_ESPACO_SUBMIT_S = 0.8


def _espacar_submit() -> None:
    with _submit_gate:
        espera = _ultimo_submit[0] + _ESPACO_SUBMIT_S - time.time()
        if espera > 0:
            time.sleep(espera)
        _ultimo_submit[0] = time.time()


def submit(image_path, prompt: str, duration_s: int = 5, resolution: str = "720p",
           model: str = "veo_fast", gerar_audio: bool = False) -> dict:
    """Enfileira a geração i2v e retorna {request_id (operation), endpoint (model_id)}.
    gerar_audio=True: fala/áudio NATIVO do Veo (cenas de fala); False: b-roll mudo."""
    _espacar_submit()
    # motor="veo" com um modelo_api de outro backend (ex.: seedance_lite) cai no padrao da casa.
    model_id = MODEL_MAP.get(model) or (model if model.startswith("veo-") else MODEL_MAP["veo_lite"])
    b64, mime = _keyframe_9x16_b64(Path(image_path))
    body = {
        "instances": [{"prompt": prompt, "image": {"bytesBase64Encoded": b64, "mimeType": mime}}],
        "parameters": {
            "aspectRatio": "9:16",
            "sampleCount": 1,
            "durationSeconds": _veo_dur(duration_s),
            "generateAudio": bool(gerar_audio),  # True: fala nativa; False: b-roll (voz na montagem)
            "resolution": "720p" if str(resolution).startswith("720") else "1080p",
        },
    }
    op = _post(f"{_base()}/{model_id}:predictLongRunning", body, _token())
    name = op.get("name")
    if not name:
        raise RuntimeError(f"Veo não devolveu operation name: {json.dumps(op)[:400]}")
    return {"request_id": name, "endpoint": model_id,
            "status_url": name, "response_url": model_id}


def aguardar(operation: str, model_id: str, output_path, timeout: int = 900,
             cancel_event=None) -> str:
    """Faz o poll da operação até done e escreve o mp4 em output_path."""
    output_path = Path(output_path)
    fetch_url = f"{_base()}/{model_id}:fetchPredictOperation"
    fim = time.time() + timeout
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Geração interrompida pelo usuário (o job no Veo segue até o fim).")
        if time.time() > fim:
            raise RuntimeError("Timeout aguardando o Veo (use Regerar > Retomar).")
        st = _post(fetch_url, {"operationName": operation}, _token())
        if st.get("done"):
            if st.get("error"):
                raise RuntimeError(f"Veo reportou falha: {json.dumps(st['error'])[:600]}")
            break
        time.sleep(8)

    resp = st.get("response", {})
    vids = resp.get("videos") or resp.get("generatedSamples") or []
    data = None
    for v in vids:
        data = (v.get("bytesBase64Encoded")
                or (v.get("video") or {}).get("bytesBase64Encoded"))
        if data:
            break
    if not data:
        raise RuntimeError(f"Resposta do Veo sem vídeo: {json.dumps(resp)[:600]}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp.mp4")
    tmp.write_bytes(base64.b64decode(data))
    tmp.replace(output_path)
    return str(output_path)


# Erros TRANSITÓRIOS do Veo/Vertex (throttle/sobrecarga): valem retry com backoff, não falha final.
# Ex.: {"code": 8, "message": "The service is currently experiencing high load..."} (RESOURCE_EXHAUSTED).
_TRANSIENTE = ("code\": 8", "code': 8", "high load", "resource_exhausted", "unavailable",
               "currently experiencing", "try again later", "overloaded", "rate limit",
               "(429)", "(500)", "(502)", "(503)", "(504)", "deadline", "timeout")
# Backoff base entre tentativas (segundos). 7 tentativas, ~5min de orçamento — throttle
# transitório do Veo raramente dura tanto. Jitter ±35% decorrelaciona as 6 threads.
_BACKOFF_S = (8, 16, 28, 45, 70, 100)


def _cancelado(cancel_event) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def generate(image_path, prompt: str, output_path, duration_s: int = 5,
             resolution: str = "720p", model: str = "veo_fast",
             timeout: int = 900, cancel_event=None, request_id: str | None = None,
             on_submit=None, gerar_audio: bool = False, **_ignored) -> str:
    """Gera 1 clipe i2v no Veo. on_submit(info) é chamado após o submit (persistência).
    request_id no formato 'model_id::operation' só retoma o poll (não paga de novo).
    gerar_audio=True: fala/áudio nativo (cenas de fala).

    Erros transitórios do Veo (sobrecarga/throttle: code 8, 'high load', 429/503) são
    reenviados automaticamente com backoff — antes qualquer pico derrubava a cena."""
    retomar = bool(request_id and "::" in request_id)
    ultimo = None
    for i in range(len(_BACKOFF_S) + 1):
        try:
            if retomar:
                model_id, operation = request_id.split("::", 1)
            else:
                info = submit(image_path, prompt, duration_s=duration_s,
                              resolution=resolution, model=model, gerar_audio=gerar_audio)
                if on_submit:
                    on_submit(info)
                model_id, operation = info["endpoint"], info["request_id"]
            return aguardar(operation, model_id, output_path,
                            timeout=timeout, cancel_event=cancel_event)
        except RuntimeError as e:
            ultimo = e
            msg = str(e).lower()
            transitorio = any(t in msg for t in _TRANSIENTE)
            # Não repete se: retomando um op já com erro, cancelado, acabou o orçamento de
            # tentativas, ou o erro é permanente (prompt/quota fixa). Aí falha de vez.
            if retomar or _cancelado(cancel_event) or i >= len(_BACKOFF_S) or not transitorio:
                raise
            espera = _BACKOFF_S[i] * random.uniform(0.65, 1.35)   # backoff com jitter ±35%
            fim = time.time() + espera                            # espera respeitando o cancelamento
            while time.time() < fim:
                if _cancelado(cancel_event):
                    raise
                time.sleep(1)
    raise ultimo  # inalcançável (o loop sempre retorna ou levanta)
