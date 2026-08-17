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
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

REGION = os.environ.get("VEO_REGION", "us-central1")

# Slugs -> modelos publicados no Vertex. Se o Google renomear, ajuste SÓ aqui.
MODEL_MAP = {
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
    raise RuntimeError("gcloud não encontrado. Instale o Google Cloud SDK e rode 'gcloud auth login'.")


def _project() -> str:
    p = (os.environ.get("VEO_PROJECT") or "").strip()
    if p:
        return p
    try:
        from workspace import carregar_config
        p = (carregar_config().get("video", {}).get("veo_project") or "").strip()
    except Exception:  # noqa: BLE001
        p = ""
    if not p:
        raise RuntimeError("VEO_PROJECT não configurado (.env) nem [video].veo_project no config.toml.")
    return p


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no Windows, não abre console do gcloud
_tok_cache = {"val": None, "exp": 0.0}


def _token() -> str:
    """Access token do gcloud, cacheado ~45min. Sem cache seria 1 chamada a cada poll (8s),
    piscando um console do Windows toda vez."""
    now = time.time()
    if _tok_cache["val"] and now < _tok_cache["exp"]:
        return _tok_cache["val"]
    val = subprocess.check_output([_gcloud(), "auth", "print-access-token"],
                                  text=True, creationflags=_NO_WINDOW).strip()
    _tok_cache["val"] = val
    _tok_cache["exp"] = now + 2700
    return val


def _base() -> str:
    proj = _project()
    return (f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{proj}"
            f"/locations/{REGION}/publishers/google/models")


def _post(url: str, body: dict, token: str, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # noqa: PERF203
        raise RuntimeError(f"Vertex/Veo recusou ({e.code}): {e.read().decode(errors='replace')[:600]}")


def submit(image_path, prompt: str, duration_s: int = 5, resolution: str = "720p",
           model: str = "veo_fast", gerar_audio: bool = False) -> dict:
    """Enfileira a geração i2v e retorna {request_id (operation), endpoint (model_id)}.
    gerar_audio=True: fala/áudio NATIVO do Veo (cenas de fala); False: b-roll mudo."""
    # motor="veo" com um modelo_api de outro backend (ex.: seedance_lite) cai no veo_fast.
    model_id = MODEL_MAP.get(model) or (model if model.startswith("veo-") else MODEL_MAP["veo_fast"])
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


def generate(image_path, prompt: str, output_path, duration_s: int = 5,
             resolution: str = "720p", model: str = "veo_fast",
             timeout: int = 900, cancel_event=None, request_id: str | None = None,
             on_submit=None, gerar_audio: bool = False, **_ignored) -> str:
    """Gera 1 clipe i2v no Veo. on_submit(info) é chamado após o submit (persistência).
    request_id no formato 'model_id::operation' só retoma o poll (não paga de novo).
    gerar_audio=True: fala/áudio nativo (cenas de fala)."""
    if request_id and "::" in request_id:
        model_id, operation = request_id.split("::", 1)
    else:
        info = submit(image_path, prompt, duration_s=duration_s,
                      resolution=resolution, model=model, gerar_audio=gerar_audio)
        if on_submit:
            on_submit(info)
        model_id, operation = info["endpoint"], info["request_id"]
    return aguardar(operation, model_id, output_path,
                    timeout=timeout, cancel_event=cancel_event)
