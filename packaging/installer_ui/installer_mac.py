"""Instalador do Ads Express para macOS — janela HTML premium (pywebview).

Espelha o instalador do Windows (installer.py + installer.html) com o MESMO visual,
adaptando só a LÓGICA pro Mac. Empacotado com PyInstaller (AdsExpress_installer_mac.spec)
embutindo:
  - payload/Ads Express.app  -> o app já buildado (BUNDLE do AdsExpress_mac.spec)
  - installer_mac.html       -> a UI (vira data URI o ícone)
  - app-1024.png             -> ícone mostrado na UI
  - _default_config/         -> config.toml semente

Fluxo (tudo GUI, sem terminal pro usuário):
  1. Copia o "Ads Express.app" pra /Applications (fallback ~/Applications) e tira a quarentena.
  2. Semeia ~/Library/Application Support/Ads Express/config/config.toml.
  3. Instala o Node.js (baixa o .pkg universal oficial e roda com UMA janela nativa de
     senha do Mac — sem depender de Homebrew).
  4. Instala as CLIs claude e codex via npm num prefixo do usuário (SEM sudo).
  5. Grava config/cli_paths.env com os caminhos absolutos (o .app não herda o PATH do shell).
  6. Etapa de logins: os mesmos 3 botões (Claude/ChatGPT/Google) da tela inicial do app.

Idempotente: pode rodar de novo; só instala o que falta.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

logging.getLogger("pywebview").setLevel(logging.CRITICAL)
import webview  # noqa: E402

APP_NAME = "Ads Express"
APP_BUNDLE = "Ads Express.app"
VERSION = "1.1.0"

# Veo (vídeo): projeto GCP do crédito + chave de serviço embutida pelo CI (GitHub secret
# GCP_SA_KEY → packaging/default_config/veo_sa.json → _default_config/veo_sa.json). Com
# ela o instalador ativa o Google sozinho — sem 'gcloud auth login' na mão.
VEO_PROJECT = "capable-fuze-506422-c2"
SA_KEY_RES = "_default_config/veo_sa.json"

CLAUDE_PKG = "@anthropic-ai/claude-code"
CODEX_PKG = "@openai/codex"
NODE_FALLBACK = "v20.17.0"  # LTS conhecido, caso o index.json da nodejs.org não responda

APP_SUPPORT = Path.home() / "Library" / "Application Support" / APP_NAME
CONFIG_DIR = APP_SUPPORT / "config"
NPM_PREFIX = APP_SUPPORT / "npm-global"  # prefixo npm do usuário → binários sem sudo


def _res(nome: str) -> Path:
    """Recurso embutido (no .app congelado vive em _MEIPASS; no fonte, ao lado)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / nome


def _ssl_ctx() -> ssl.SSLContext:
    """Contexto SSL com CA bundle. Num .app congelado o OpenSSL não acha os certs do
    sistema sozinho — usa o certifi (bundlado) pra o HTTPS da nodejs.org funcionar."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


# --- PATH: o processo do instalador precisa enxergar node/npm/claude/codex ----------
def _augment_path() -> None:
    extra = [
        str(NPM_PREFIX / "bin"),
        "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
        str(Path.home() / ".nvm" / "current" / "bin"),
    ]
    atual = os.environ.get("PATH", "")
    partes = [p for p in extra if p not in atual.split(os.pathsep)]
    os.environ["PATH"] = os.pathsep.join(partes + ([atual] if atual else []))


def _which(nome: str) -> str | None:
    return shutil.which(nome)


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# --- detecção de "conectado" (mesma heurística de app/logins.py, sem rede) -----------
def _claude_conectado() -> bool:
    home = Path.home()
    if (home / ".claude" / ".credentials.json").exists():
        return True
    j = home / ".claude.json"
    if j.exists():
        try:
            dados = json.loads(j.read_text(encoding="utf-8"))
            return bool(dados.get("oauthAccount") or dados.get("primaryApiKey"))
        except Exception:  # noqa: BLE001
            return True
    return False


def _codex_conectado() -> bool:
    return (Path.home() / ".codex" / "auth.json").exists()


def _gcloud_conectado(exe: str) -> bool:
    try:
        r = _run([exe, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                 timeout=15)
        return bool((r.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return False


def _status_um(tool: str) -> dict:
    if tool == "claude":
        exe = _which("claude")
        return {"instalado": bool(exe), "conectado": bool(exe) and _claude_conectado()}
    if tool == "codex":
        exe = _which("codex")
        return {"instalado": bool(exe), "conectado": bool(exe) and _codex_conectado()}
    if tool == "gcloud":
        exe = _which("gcloud")
        return {"instalado": bool(exe), "conectado": bool(exe) and _gcloud_conectado(exe)}
    return {"instalado": False, "conectado": False}


def _abrir_login_terminal(argv: list[str], titulo: str) -> None:
    """Abre o login (interativo/navegador) numa janela do Terminal — igual app/logins.py."""
    linha = " ".join("'" + a.replace("'", "'\\''") + "'" for a in argv)
    script = (f'tell application "Terminal" to do script "{linha}"\n'
              'tell application "Terminal" to activate')
    subprocess.Popen(["osascript", "-e", script])


# --- Node.js: baixa o .pkg universal oficial e instala com senha nativa (1x) ---------
def _node_ok() -> bool:
    exe = _which("node")
    if not exe:
        return False
    try:
        r = _run([exe, "-p", "process.versions.node"], timeout=20)
        maj = int((r.stdout or "0").strip().split(".")[0] or 0)
        return maj >= 18
    except Exception:  # noqa: BLE001
        return False


def _node_pkg_url() -> str:
    try:
        with urllib.request.urlopen("https://nodejs.org/dist/index.json", timeout=20,
                                    context=_ssl_ctx()) as r:
            dados = json.loads(r.read().decode())
        ver = next((d["version"] for d in dados if d.get("lts")), NODE_FALLBACK)
    except Exception:  # noqa: BLE001
        ver = NODE_FALLBACK
    return f"https://nodejs.org/dist/{ver}/node-{ver}.pkg"


def _instalar_node(prog) -> None:
    if _node_ok():
        return
    url = _node_pkg_url()
    prog(48, "Baixando o Node.js…")
    destino = Path(os.environ.get("TMPDIR", "/tmp")) / "node-adsexpress.pkg"
    with urllib.request.urlopen(url, timeout=120, context=_ssl_ctx()) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f)
    prog(58, "Instalando o Node.js (digite sua senha do Mac)…")
    # installer -pkg exige root: osascript pede a senha na janela NATIVA do macOS.
    shell = f"/usr/sbin/installer -pkg {shlex.quote(str(destino))} -target /"
    r = _run(["osascript", "-e", f'do shell script "{shell}" with administrator privileges'])
    if r.returncode != 0:
        raise RuntimeError("Instalação do Node.js cancelada ou falhou. "
                           + (r.stderr or "").strip()[:180])
    _augment_path()
    if not _which("npm"):
        raise RuntimeError("Node instalado, mas o npm não apareceu no PATH.")


# --- CLIs via npm (prefixo do usuário: sem sudo) ------------------------------------
def _instalar_npm(pkg: str) -> None:
    npm = _which("npm")
    if not npm:
        raise RuntimeError("npm indisponível — o Node.js não instalou corretamente.")
    NPM_PREFIX.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, NPM_CONFIG_PREFIX=str(NPM_PREFIX))
    r = _run([npm, "install", "-g", pkg], env=env, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"Falha ao instalar {pkg}: " + (r.stderr or "").strip()[:180])


# --- config.toml semente + cli_paths.env --------------------------------------------
def _semear_config() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    alvo = CONFIG_DIR / "config.toml"
    if alvo.exists():
        return
    modelo = _res("_default_config/config.toml")
    if modelo.exists():
        shutil.copy2(modelo, alvo)
    else:
        alvo.write_text(
            '[geracao]\nbackend = "codex"\nsize = "1024x1024"\ntimeout = 600\nworkers = 6\n'
            '[app]\nffmpeg = ""\n', encoding="utf-8")


def _forcar_veo_project() -> None:
    """Garante veo_project no config MESMO em reinstalação (config.toml já existe). O
    usuário pediu que sobrescreva: troca SÓ a linha do veo_project, preservando o resto
    das configs (voz, workers, etc.). É por isso que não dá pra confiar no _semear_config,
    que não toca num config.toml existente."""
    alvo = CONFIG_DIR / "config.toml"
    if not alvo.exists():
        return
    try:
        txt = alvo.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return
    linha = f'veo_project = "{VEO_PROJECT}"'
    if re.search(r"(?m)^\s*veo_project\s*=.*$", txt):
        novo = re.sub(r"(?m)^\s*veo_project\s*=.*$", linha, txt)
    elif re.search(r"(?m)^\[video\]\s*$", txt):
        novo = re.sub(r"(?m)^\[video\]\s*$", "[video]\n" + linha, txt, count=1)
    else:
        novo = txt.rstrip() + f"\n\n[video]\n{linha}\n"
    if novo != txt:
        try:
            alvo.write_text(novo, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _copiar_sa_key() -> Path | None:
    """Copia a chave de serviço embutida pra pasta gravável de config (persiste entre
    updates e é o que o app lê em runtime). None se este build não trouxe chave."""
    origem = _res(SA_KEY_RES)
    try:
        if not origem.exists() or origem.stat().st_size == 0:
            return None
    except Exception:  # noqa: BLE001
        return None
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    destino = CONFIG_DIR / "veo_sa.json"
    try:
        shutil.copy2(origem, destino)
        os.chmod(destino, 0o600)  # credencial: só o dono lê
        return destino
    except Exception:  # noqa: BLE001
        return origem


def _ativar_service_account() -> None:
    """Ativa a conta de serviço do Veo automaticamente (instalar → Google já configurado,
    sem login no navegador). Se o build não trouxe a chave, ou o gcloud ainda não está
    instalado, só segue — o backend do app ativa via chave quando o gcloud existir."""
    key = _copiar_sa_key()
    if not key:
        return
    g = _which("gcloud")
    if not g:
        return
    try:
        _run([g, "auth", "activate-service-account", "--key-file", str(key)], timeout=60)
        try:
            proj = json.loads(Path(key).read_text(encoding="utf-8")).get("project_id")
            if proj:
                _run([g, "config", "set", "project", proj], timeout=30)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def _semear_produtos() -> None:
    """Copia os produtos embutidos pra pasta de dados do usuário, SEM sobrescrever o que
    já existe (adiciona os que faltam; preserva o trabalho local em reinstalações).
    O app lê de config/products (novo) e products (legado) — semeia os dois."""
    alvos = [
        (_res("_seed/config_products"), CONFIG_DIR / "products"),
        (_res("_seed/products"), APP_SUPPORT / "products"),
        (_res("_seed/config_avatares"), CONFIG_DIR / "avatares"),
        (_res("_seed/config_influenciadores"), CONFIG_DIR / "influenciadores"),
    ]
    for origem, destino in alvos:
        if not origem.exists():
            continue
        destino.mkdir(parents=True, exist_ok=True)
        for item in origem.iterdir():
            alvo = destino / item.name
            if alvo.exists():
                continue  # já existe nesta máquina: não sobrescreve
            try:
                if item.is_dir():
                    shutil.copytree(item, alvo)
                else:
                    shutil.copy2(item, alvo)
            except Exception:  # noqa: BLE001 — um produto problemático não trava a instalação
                pass


def _gravar_cli_paths() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    linhas = [
        "# Caminhos ABSOLUTOS gravados pelo instalador. O app adiciona estes diretórios",
        "# ao PATH em runtime (um .app do macOS NÃO herda o PATH do Terminal).",
    ]
    for tool in ("node", "npm", "claude", "codex", "ffmpeg", "gcloud"):
        p = _which(tool)
        if p:
            linhas.append(f"{tool.upper()}_PATH={p}")
    (CONFIG_DIR / "cli_paths.env").write_text("\n".join(linhas) + "\n", encoding="utf-8")


# --- Copiar o app pra /Applications -------------------------------------------------
def _payload_app() -> Path:
    """Acha o 'Ads Express.app' embutido. O build_mac.sh copia ele pra
    Contents/Resources/payload/ (fora do PyInstaller). Tenta também _MEIPASS e ao lado
    do fonte, por robustez."""
    cands = []
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()          # Contents/MacOS/Ads Express Installer
        cands.append(exe.parent.parent / "Resources" / "payload" / APP_BUNDLE)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / "payload" / APP_BUNDLE)
    cands.append(_res("payload") / APP_BUNDLE)
    for c in cands:
        if c.exists():
            return c
    raise RuntimeError("Payload do app não encontrado dentro do instalador.")


def _instalar_app(prog) -> Path:
    payload = _payload_app()
    for base in (Path("/Applications"), Path.home() / "Applications"):
        base.mkdir(parents=True, exist_ok=True)
        dest = base / APP_BUNDLE
        try:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            # ditto preserva symlinks, permissões e a assinatura do bundle (melhor que cp).
            r = _run(["/usr/bin/ditto", str(payload), str(dest)], timeout=600)
            if r.returncode != 0:
                raise OSError(r.stderr or "ditto falhou")
            # App vindo de build local não costuma ter quarentena, mas garantimos.
            _run(["/usr/bin/xattr", "-dr", "com.apple.quarantine", str(dest)])
            return dest
        except OSError:
            continue  # sem permissão em /Applications → tenta ~/Applications
    raise RuntimeError("Não consegui copiar o app nem pra /Applications nem pra ~/Applications.")


class API:
    def __init__(self):
        self.window = None
        self.app_path: Path | None = None

    # -- chamados pela UI --
    def instalar(self):
        threading.Thread(target=self._instalar, daemon=True).start()

    def status(self) -> dict:
        _augment_path()
        return {t: _status_um(t) for t in ("claude", "codex", "gcloud")}

    def login(self, tool: str) -> dict:
        _augment_path()
        argv = None
        if tool == "claude" and _which("claude"):
            argv = [_which("claude")]                 # entra no modo interativo (/login)
        elif tool == "codex" and _which("codex"):
            argv = [_which("codex"), "login"]
        elif tool == "gcloud":
            g = _which("gcloud")
            if g:
                argv = [g, "auth", "login"]
            else:
                return {"ok": False, "msg": "Google Cloud (opcional/vídeo): instale o SDK depois."}
        if not argv:
            return {"ok": False, "msg": f"{tool}: ainda não instalado."}
        try:
            _abrir_login_terminal(argv, f"Login {tool}")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": f"Não consegui abrir o login: {e}"}
        return {"ok": True}

    def abrir_app(self):
        alvo = self.app_path or (Path("/Applications") / APP_BUNDLE)
        try:
            # run (não Popen): espera o 'open' pedir o launch pro LaunchServices antes de
            # a gente encerrar — o app abre independente do instalador.
            subprocess.run(["/usr/bin/open", str(alvo)], timeout=20)
        except Exception:  # noqa: BLE001
            pass
        self._sair()

    def fechar(self):
        self._sair()

    def _sair(self):
        """Encerra o instalador DE VERDADE. No backend Cocoa, window.destroy() chamado
        da thread do js_api às vezes não termina o NSApplication loop — a janela fica
        'carregando' (beachball) e só sai forçando. os._exit garante o encerramento
        (o instalador já concluiu o trabalho quando isto é chamado)."""
        try:
            if self.window:
                self.window.destroy()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)

    # -- interno --
    def _prog(self, pct, msg):
        if self.window:
            self.window.evaluate_js(
                f"window.setProgress({int(pct)}, {json.dumps(msg, ensure_ascii=False)})")

    def _instalar(self):
        try:
            _augment_path()
            self._prog(3, "Preparando…")
            _semear_config()
            _forcar_veo_project()      # garante a conta/projeto do Veo mesmo em reinstalação
            self._prog(6, "Copiando seus produtos e avatares…")
            _semear_produtos()

            self._prog(10, "Copiando o app pra Aplicativos…")
            self.app_path = _instalar_app(self._prog)
            self._prog(45, "App instalado.")

            _instalar_node(self._prog)   # 48–60 (pode pedir senha)

            self._prog(66, "Instalando o Claude…")
            _instalar_npm(CLAUDE_PKG)
            self._prog(82, "Instalando o Codex…")
            _instalar_npm(CODEX_PKG)

            self._prog(94, "Salvando configurações…")
            _augment_path()
            _gravar_cli_paths()

            self._prog(97, "Configurando o Google (Veo)…")
            _ativar_service_account()  # ativa a chave embutida: Veo sem login manual

            self._prog(100, "Concluído")
            if self.window:
                self.window.evaluate_js("window.instalado()")
        except Exception as e:  # noqa: BLE001
            if self.window:
                self.window.evaluate_js(f"window.setErro({json.dumps(str(e), ensure_ascii=False)})")


def _html() -> str:
    html = _res("installer_mac.html").read_text(encoding="utf-8")
    ico = base64.b64encode(_res("app-1024.png").read_bytes()).decode()
    return html.replace("{{ICON}}", f"data:image/png;base64,{ico}").replace("{{VERSION}}", VERSION)


def main():
    if getattr(sys, "frozen", False):
        try:
            sys.stderr = open(os.devnull, "w")  # noqa: SIM115
        except OSError:
            pass
    api = API()
    win = webview.create_window(
        APP_NAME, html=_html(), js_api=api,
        width=540, height=660, resizable=False,
        background_color="#0d0d0f",
    )
    api.window = win
    webview.start()


if __name__ == "__main__":
    main()
