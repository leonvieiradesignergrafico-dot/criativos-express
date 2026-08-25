"""Logins das ferramentas externas, disparados de DENTRO do app (tela inicial).

Três contas que o app usa por baixo:
  - claude  -> plano Claude (toda a inteligência de texto)
  - codex   -> plano ChatGPT (geração de imagem/keyframes)
  - gcloud  -> Google Cloud (Veo/Omni, geração de vídeo — usa o access token do gcloud)

Cada login é um fluxo INTERATIVO (abre o navegador). Por isso o botão não roda o
comando "escondido": ele abre uma janela de terminal com o comando, onde o usuário
acompanha o passo a passo. A detecção de "conectado" é best-effort e sem rede.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# gcloud costuma não entrar no PATH no Windows; mesmo default do veo_backend.py.
_GCLOUD_DEFAULT_WIN = r"C:\Users\Leon\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"

_IS_WIN = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no Windows não pisca console


def _which_cli(nome: str) -> str | None:
    """Acha o executável de uma CLI, cobrindo os shims de npm global no Windows."""
    exe = shutil.which(nome)
    if exe:
        return exe
    # npm global no Windows instala .cmd em %APPDATA%\npm.
    if _IS_WIN:
        appdata = os.environ.get("APPDATA")
        if appdata:
            for ext in (".cmd", ".exe", ""):
                cand = Path(appdata) / "npm" / f"{nome}{ext}"
                if cand.exists():
                    return str(cand)
    return None


def _gcloud_exe() -> str | None:
    exe = os.environ.get("GCLOUD_PATH") or shutil.which("gcloud")
    if exe:
        return exe
    if _IS_WIN and Path(_GCLOUD_DEFAULT_WIN).exists():
        return _GCLOUD_DEFAULT_WIN
    return None


# --- detecção de "conectado" (heurística, sem rede quando dá) -------------------
def _claude_conectado(exe: str | None = None) -> bool:
    # Fonte autoritativa: a propria CLI. `claude auth status --json` devolve
    # {"loggedIn": bool} sem abrir sessao. So caimos na heuristica de arquivo
    # abaixo se a CLI for antiga (sem o subcomando 'auth') ou nao responder.
    if exe:
        try:
            r = subprocess.run([exe, "auth", "status", "--json"], capture_output=True,
                               text=True, timeout=15, creationflags=_NO_WINDOW)
            dados = json.loads(r.stdout or "{}")
            if "loggedIn" in dados:
                return bool(dados["loggedIn"])
        except Exception:  # noqa: BLE001 — sem 'auth'/timeout: usa a heuristica
            pass
    home = Path.home()
    cred = home / ".claude" / ".credentials.json"
    if cred.exists():
        return True
    # Alguns builds guardam a conta OAuth no ~/.claude.json.
    j = home / ".claude.json"
    if j.exists():
        try:
            dados = json.loads(j.read_text(encoding="utf-8"))
            return bool(dados.get("oauthAccount") or dados.get("primaryApiKey"))
        except Exception:  # noqa: BLE001 — arquivo malformado = trata como não confirmado
            return True  # existe mas não deu pra ler: não afirmar desconectado
    return False


def _codex_conectado() -> bool:
    return (Path.home() / ".codex" / "auth.json").exists()


def _gcloud_conectado(exe: str) -> bool:
    """Tem conta ATIVA no gcloud? Usa `auth list` (rápido, cacheado localmente)."""
    try:
        out = subprocess.check_output(
            [exe, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
            text=True, creationflags=_NO_WINDOW, timeout=15,
            stderr=subprocess.DEVNULL)
        return bool(out.strip())
    except Exception:  # noqa: BLE001 — sem gcloud/erro = não confirmado
        return False


# --- metadados das 3 contas -----------------------------------------------------
def _status_um(tool: str) -> dict:
    if tool == "claude":
        exe = _which_cli("claude")
        return {"instalado": bool(exe), "conectado": bool(exe) and _claude_conectado(exe)}
    if tool == "codex":
        exe = _which_cli("codex")
        return {"instalado": bool(exe), "conectado": bool(exe) and _codex_conectado()}
    if tool == "gcloud":
        exe = _gcloud_exe()
        return {"instalado": bool(exe), "conectado": bool(exe) and _gcloud_conectado(exe)}
    return {"instalado": False, "conectado": False}


_META = {
    "claude": {"label": "Claude", "conta": "plano Claude"},
    "codex": {"label": "ChatGPT", "conta": "plano ChatGPT (Codex)"},
    "gcloud": {"label": "Google Cloud", "conta": "vídeo Veo/Omni"},
}


def status_todos() -> dict:
    """Estado das 3 contas pro front pintar os botões."""
    out = {}
    for tool, meta in _META.items():
        st = _status_um(tool)
        out[tool] = {**meta, **st}
    return out


# --- disparo do login (abre terminal visível) -----------------------------------
def _comando_login(tool: str) -> list[str] | None:
    """Retorna o argv do comando de login, ou None se a CLI não foi achada."""
    if tool == "claude":
        exe = _which_cli("claude")
        # `claude auth login` faz o login e ENCERRA. Nao abrir o `claude` puro: ele
        # entra na sessao interativa de uso e a janela fica presa nela.
        return [exe, "auth", "login"] if exe else None
    if tool == "codex":
        exe = _which_cli("codex")
        return [exe, "login"] if exe else None
    if tool == "gcloud":
        exe = _gcloud_exe()
        # O Veo usa o access token de USUÁRIO (gcloud auth print-access-token),
        # então o login certo é o de usuário — não o application-default.
        return [exe, "auth", "login"] if exe else None
    return None


def _comando_instalar_gcloud() -> list[str] | None:
    """argv pra instalar o Google Cloud SDK (grátis) pela loja do SO, ou None."""
    if _IS_WIN and shutil.which("winget"):
        return ["winget", "install", "-e", "--id", "Google.CloudSDK"]
    if _IS_MAC and shutil.which("brew"):
        return ["brew", "install", "--cask", "google-cloud-sdk"]
    return None


def _abrir_em_terminal(argv: list[str], titulo: str) -> None:
    """Abre uma janela de terminal rodando `argv` (fluxo interativo/navegador)."""
    if _IS_WIN:
        # start abre nova janela; cmd /k mantém aberta pra ver o resultado.
        linha = " ".join(_quote_win(a) for a in argv)
        subprocess.Popen(f'start "{titulo}" cmd /k {linha}', shell=True)
        return
    if _IS_MAC:
        linha = " ".join(_quote_sh(a) for a in argv)
        script = f'tell application "Terminal" to do script "{linha}"\n' \
                 'tell application "Terminal" to activate'
        subprocess.Popen(["osascript", "-e", script])
        return
    # Linux (dev): tenta um emulador comum; se falhar, roda destacado.
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        if shutil.which(term):
            subprocess.Popen([term, "-e", *argv])
            return
    subprocess.Popen(argv)


def _quote_win(a: str) -> str:
    return f'"{a}"' if " " in a else a


def _quote_sh(a: str) -> str:
    return "'" + a.replace("'", "'\\''") + "'"


def iniciar_login(tool: str) -> dict:
    """Dispara o login da ferramenta. Retorna {ok, msg}."""
    if tool not in _META:
        return {"ok": False, "msg": f"Ferramenta desconhecida: {tool}"}
    argv = _comando_login(tool)
    if not argv:
        # gcloud é o único que dá pra instalar de dentro do app (winget/brew, grátis).
        if tool == "gcloud":
            inst = _comando_instalar_gcloud()
            if inst:
                try:
                    _abrir_em_terminal(inst, "Instalar Google Cloud SDK")
                except Exception as e:  # noqa: BLE001
                    return {"ok": False, "msg": f"Não consegui abrir a instalação: {e}"}
                return {"ok": True, "acao": "instalar",
                        "msg": "Instalando o Google Cloud SDK numa janela — quando terminar, "
                               "FECHE e reabra o app, depois clique de novo pra logar."}
            return {"ok": False, "msg": "Instale o Google Cloud SDK: "
                                        "https://cloud.google.com/sdk/docs/install"}
        nome = _META[tool]["label"]
        return {"ok": False, "msg": f"{nome}: rode o Setup pra instalar a CLI ({tool}) primeiro."}
    try:
        _abrir_em_terminal(argv, f"Login {_META[tool]['label']}")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"Não consegui abrir o login: {e}"}
    return {"ok": True, "msg": "Abri o login numa janela de terminal — siga no navegador."}


# --- VEO_PROJECT (id do projeto GCP pro fluxo de vídeo) -------------------------
def get_veo_project() -> str:
    """Lê o VEO_PROJECT atual (env tem prioridade; senão [video].veo_project do config)."""
    p = (os.environ.get("VEO_PROJECT") or "").strip()
    if p:
        return p
    try:
        import workspace
        cfg = workspace.carregar_config()
        return str((cfg.get("video") or {}).get("veo_project") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def set_veo_project(pid: str) -> dict:
    """Grava [video].veo_project no config.toml (regex simples, preserva o resto)."""
    import re as _re
    import workspace
    pid = (pid or "").strip()
    alvo = workspace.CONFIG_DIR / "config.toml"
    if not alvo.exists():
        alvo = workspace._config_file("config.toml")
    try:
        txt = alvo.read_text(encoding="utf-8")
        novo, n = _re.subn(r'(?m)^(\s*veo_project\s*=\s*).*$',
                           rf'\1"{pid}"', txt, count=1)
        if n == 0:  # não tinha a chave: acrescenta sob [video] ou no fim
            novo = txt.rstrip() + f'\n\n[video]\nveo_project = "{pid}"\n' \
                if "[video]" not in txt else \
                _re.sub(r'(?m)^\[video\]\s*$', f'[video]\nveo_project = "{pid}"', txt, count=1)
        alvo.write_text(novo, encoding="utf-8")
        os.environ["VEO_PROJECT"] = pid
        return {"ok": True, "veo_project": pid}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"Não consegui salvar: {e}"}
