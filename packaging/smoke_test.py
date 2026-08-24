"""Teste de fumaça do Ads Express — roda DENTRO do app já empacotado.

MOTIVO: o único jeito honesto de validar o build de Mac era instalar o .dmg e rodar o
pipeline inteiro (copy -> roteiro -> keyframes -> clipes) até descobrir, no último passo,
que algo quebrou (foi assim que apareceu o CERTIFICATE_VERIFY_FAILED). Este módulo
exercita, em segundos e sem gastar 1 centavo de geração, tudo que costuma quebrar num
bundle congelado: CAs/HTTPS, imports que o PyInstaller esqueceu, assets do bundle, pastas
graváveis, rotas do Flask, resolução das CLIs e o token do Google.

Uso:
    "Ads Express.app/Contents/MacOS/Ads Express" --smoke     (no app congelado)
    python packaging/smoke_test.py                            (do código-fonte)

Sai com código 1 se houver FALHA (o CI derruba o build antes de virar release).
AVISO não derruba: é o que depende da máquina do usuário (ffmpeg instalado, login feito).
"""
from __future__ import annotations

import json
import os
import platform
import socket
import ssl
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path

OK, AVISO, FALHA = "OK", "AVISO", "FALHA"
_res: list[tuple[str, str, str]] = []


def _reg(nivel: str, titulo: str, detalhe: str = "") -> None:
    _res.append((nivel, titulo, detalhe))
    marca = {OK: "  ok  ", AVISO: " aviso", FALHA: " FALHA"}[nivel]
    print(f"[{marca}] {titulo}" + (f" -- {detalhe}" if detalhe else ""), flush=True)


def _checar(titulo: str, fn, critico: bool = True) -> None:
    """Roda fn(); ela devolve (nivel, detalhe) ou levanta (vira FALHA/AVISO)."""
    try:
        nivel, detalhe = fn()
    except Exception as e:  # noqa: BLE001
        nivel, detalhe = (FALHA if critico else AVISO), f"{type(e).__name__}: {e}"
        if os.environ.get("SMOKE_VERBOSE"):
            traceback.print_exc()
    _reg(nivel, titulo, detalhe)


# --- 1. ambiente --------------------------------------------------------------
def _ambiente():
    congelado = getattr(sys, "frozen", False)
    return OK, (f"{platform.system()} {platform.release()} / {platform.machine()} / "
                f"Python {sys.version.split()[0]} / congelado={congelado}")


# --- 2. CAs (a causa do CERTIFICATE_VERIFY_FAILED no Mac) ---------------------
def _ca_bundle():
    ca = os.environ.get("SSL_CERT_FILE") or ""
    if ca and Path(ca).exists():
        return OK, f"SSL_CERT_FILE={ca}"
    # Fora do bundle congelado o sistema pode ter CAs próprias (Windows/Linux).
    if not getattr(sys, "frozen", False):
        return AVISO, "sem SSL_CERT_FILE (fora do app congelado, pode ser normal)"
    if sys.platform == "darwin":
        raise RuntimeError(
            "app congelado no macOS SEM bundle de CAs -- o runtime hook "
            "packaging/rthook_ssl_certs.py nao rodou ou o certifi nao foi empacotado. "
            "E EXATAMENTE isso que quebra a geracao de clipes no Veo.")
    return AVISO, "sem SSL_CERT_FILE (no Windows o ssl usa a cert store do SO)"


# --- 3. HTTPS de verdade (é o que o Veo faz) ---------------------------------
_HOSTS = [
    ("Vertex AI (Veo)", "https://us-central1-aiplatform.googleapis.com/v1/projects/"
                        "smoke/locations/us-central1/publishers/google/models"),
    ("Google OAuth", "https://oauth2.googleapis.com/"),
    ("Anthropic (CLI claude)", "https://api.anthropic.com/"),
    ("npm registry (instalador)", "https://registry.npmjs.org/"),
]


def _https(url: str):
    def _f():
        req = urllib.request.Request(url, headers={"User-Agent": "AdsExpress-Smoke"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return OK, f"HTTP {r.status} (TLS validou)"
        except urllib.error.HTTPError as e:
            # 401/403/404 é ótimo: significa que o TLS passou e o servidor respondeu.
            return OK, f"HTTP {e.code} (TLS validou)"
        except urllib.error.URLError as e:
            razao = getattr(e, "reason", e)
            if isinstance(razao, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(razao):
                raise RuntimeError(f"TLS FALHOU: {razao}") from None
            return AVISO, f"rede indisponivel ({razao})"
    return _f


# --- 4. imports (pega hiddenimport faltando no spec) --------------------------
_MODULOS = [
    "flask", "jinja2", "werkzeug", "PIL.Image", "dotenv", "certifi",
    "workspace", "gerar", "gerar_ugc",
    "app.server", "app.ugc_web", "app.claude_bridge", "app.codex_text_bridge",
    "app.logins", "app.console_log",
    "app.pipeline.clipes", "app.pipeline.keyframes", "app.pipeline.montagem",
    "app.pipeline.qualidade", "app.pipeline.roteiro", "app.pipeline.voz",
    "app.pipeline.fala_veo", "app.pipeline.copy_ugc", "app.pipeline.formatos_video",
    "app.pipeline.inserts", "app.pipeline._status",
    "backends.veo_backend", "backends.codex_backend", "backends.api_backend",
    "backends.tts_edge_backend", "backends.tts_eleven_backend",
    # deps de import tardio: se faltarem, o erro so apareceria ao clicar "testar voz".
    "requests", "edge_tts",
]
if sys.platform == "darwin":
    _MODULOS += ["webview", "webview.platforms.cocoa", "objc", "AppKit", "WebKit"]
elif os.name == "nt":
    _MODULOS += ["webview"]


def _imports():
    import importlib
    faltando = []
    for m in _MODULOS:
        try:
            importlib.import_module(m)
        except Exception as e:  # noqa: BLE001
            faltando.append(f"{m} ({type(e).__name__}: {e})")
    if faltando:
        raise RuntimeError("imports quebrados -> falta hiddenimport no .spec: "
                           + "; ".join(faltando[:8]))
    return OK, f"{len(_MODULOS)} modulos importados"


# --- 5. assets só-leitura do bundle ------------------------------------------
def _assets():
    from workspace import BUNDLE_DIR
    faltando = [str(p) for p in (
        Path(BUNDLE_DIR) / "app" / "templates" / "index.html",
        Path(BUNDLE_DIR) / "app" / "static",
        Path(BUNDLE_DIR) / "app" / "prompts",
    ) if not p.exists()]
    if faltando:
        raise RuntimeError("assets ausentes no bundle: " + ", ".join(faltando))
    return OK, f"templates/static/prompts em {BUNDLE_DIR}"


# --- 6. pastas graváveis ------------------------------------------------------
def _dados_gravaveis():
    from workspace import DATA_ROOT, ensure_user_config
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    teste = DATA_ROOT / ".smoke_write"
    teste.write_text("ok", encoding="utf-8")
    teste.unlink()
    ensure_user_config()
    return OK, f"gravavel: {DATA_ROOT}"


# --- 7. Flask (rotas + render dos templates) ---------------------------------
def _flask():
    from app.server import app as flask_app
    c = flask_app.test_client()
    r1 = c.get("/")
    r2 = c.get("/api/produtos")
    if r1.status_code != 200:
        raise RuntimeError(f"GET / devolveu {r1.status_code} (template nao renderizou)")
    if r2.status_code != 200:
        raise RuntimeError(f"GET /api/produtos devolveu {r2.status_code}")
    return OK, f"/ e /api/produtos OK ({len(r1.data)} bytes na home)"


def _porta():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 5000))
        return OK, "porta 5000 livre"
    except OSError as e:
        return AVISO, f"porta 5000 ocupada ({e}) -- a janela pode abrir em branco"
    finally:
        s.close()


# --- 8. CLIs externas (dependem da máquina do usuário) -----------------------
def _clis():
    import shutil
    import workspace  # noqa: F401 -- importar já prepara o PATH (Mac/cli_paths.env)
    achadas, faltando = [], []
    for nome in ("node", "claude", "codex", "ffmpeg", "ffprobe", "gcloud"):
        caminho = shutil.which(nome)
        (achadas if caminho else faltando).append(f"{nome}={caminho or '?'}")
    if faltando:
        return AVISO, ("nao encontradas: "
                       + ", ".join(f.split("=")[0] for f in faltando)
                       + " | achadas: " + ", ".join(achadas))
    return OK, ", ".join(achadas)


# --- 9. service account embutida (Veo sem login) -----------------------------
def _sa_embutida():
    from backends.veo_backend import _sa_key_path
    key = _sa_key_path()
    if not key:
        return AVISO, "sem chave embutida (cai no gcloud auth login do usuario)"
    dados = json.loads(Path(key).read_text(encoding="utf-8"))
    if not dados.get("client_email") or not dados.get("project_id"):
        raise RuntimeError(f"chave em {key} sem client_email/project_id")
    return OK, f"{dados['client_email']} / projeto {dados['project_id']}"


# --- 10. ponta a ponta: token do gcloud + chamada REAL (grátis) ao Vertex ----
def _vertex_token():
    """Ativa a SA, pega o token e faz um GET no modelo do Veo. Não gera vídeo (não
    custa nada), mas prova auth + projeto + permissão + TLS -- a mesma cadeia que a
    geração de clipes usa. Sem gcloud na máquina, vira AVISO."""
    import shutil
    if not shutil.which("gcloud") and not os.environ.get("GCLOUD_PATH"):
        return AVISO, "gcloud ausente -- pulo o teste ponta a ponta"
    from backends import veo_backend
    try:
        projeto = veo_backend._project()
    except Exception as e:  # noqa: BLE001
        return AVISO, f"VEO_PROJECT indefinido ({e})"
    token = veo_backend._token()
    if not token:
        raise RuntimeError("gcloud devolveu token vazio")
    url = (f"https://{veo_backend.REGION}-aiplatform.googleapis.com/v1/projects/{projeto}"
           f"/locations/{veo_backend.REGION}/publishers/google/models/"
           f"{veo_backend.MODEL_MAP['veo_fast']}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=veo_backend._ssl_ctx()) as r:
            r.read(200)
        return OK, f"token + Vertex respondendo no projeto {projeto}"
    except urllib.error.HTTPError as e:
        corpo = e.read().decode(errors="replace")[:200]
        if e.code in (401, 403):
            raise RuntimeError(f"auth recusada pelo Vertex ({e.code}): {corpo}")
        return OK, f"token valido; Vertex respondeu {e.code} (esperado p/ GET de modelo)"
    except urllib.error.URLError as e:
        # Rede caindo no runner nao pode derrubar o build; TLS quebrado, sim.
        razao = getattr(e, "reason", e)
        if isinstance(razao, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(razao):
            raise RuntimeError(f"TLS FALHOU no Vertex: {razao}") from None
        return AVISO, f"rede indisponivel ({razao})"


def rodar() -> int:
    print("=" * 72)
    print("  Ads Express -- teste de fumaca")
    print("=" * 72)
    _checar("ambiente", _ambiente)
    _checar("bundle de CAs (SSL)", _ca_bundle)
    for nome, url in _HOSTS:
        _checar(f"HTTPS: {nome}", _https(url))
    _checar("imports do bundle", _imports)
    _checar("assets so-leitura", _assets)
    _checar("pasta de dados gravavel", _dados_gravaveis)
    _checar("servidor Flask", _flask)
    _checar("porta 5000", _porta, critico=False)
    _checar("CLIs externas", _clis, critico=False)
    _checar("service account embutida", _sa_embutida, critico=False)
    _checar("Vertex/Veo ponta a ponta", _vertex_token)

    falhas = [t for n, t, _ in _res if n == FALHA]
    avisos = [t for n, t, _ in _res if n == AVISO]
    print("-" * 72)
    print(f"  {len(_res) - len(falhas) - len(avisos)} ok - {len(avisos)} aviso(s) - "
          f"{len(falhas)} falha(s)")
    if falhas:
        print("  FALHOU: " + ", ".join(falhas))
    print("=" * 72, flush=True)
    return 1 if falhas else 0


if __name__ == "__main__":
    _raiz = str(Path(__file__).resolve().parents[1])
    if _raiz not in sys.path:
        sys.path.insert(0, _raiz)
    sys.exit(rodar())
