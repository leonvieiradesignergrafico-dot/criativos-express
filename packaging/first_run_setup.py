"""Setup / Reparar — Ads Express.

Assistente de primeira execução para usuários NÃO técnicos. Verifica e instala as
dependências externas de que o app precisa (Node.js + as CLIs Claude Code e Codex),
guia o login de cada CLI e checa o ffmpeg (opcional, só vídeo).

É idempotente e re-executável: rode quantas vezes quiser ("Setup / Reparar").
Roda tanto como script (`python packaging/first_run_setup.py`) quanto como o
executável "Setup Ads Express.exe" gerado no empacotamento.

As CLIs consomem o SEU plano (Claude / ChatGPT) — o app não usa API paga por padrão.
Pacotes npm (nomes reais usados pelas pontes do app):
    - @anthropic-ai/claude-code   -> comando `claude`
    - @openai/codex               -> comando `codex`
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

# --- pacotes/CLIs (mesmos nomes que app/claude_bridge.py e backends/codex_backend.py) ---
CLAUDE_PKG = "@anthropic-ai/claude-code"
CODEX_PKG = "@openai/codex"
NODE_URL = "https://nodejs.org/en/download/prebuilt-installer"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --- Cosmético de terminal ----------------------------------------------------
def _enable_ansi() -> None:
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:  # noqa: BLE001
            pass


_C = {
    "reset": "\033[0m", "bold": "\033[1m", "green": "\033[92m", "red": "\033[91m",
    "yellow": "\033[93m", "cyan": "\033[96m", "gray": "\033[90m",
}


def c(txt: str, cor: str) -> str:
    return f"{_C.get(cor, '')}{txt}{_C['reset']}"


def titulo(txt: str) -> None:
    print("\n" + c("─" * 64, "gray"))
    print(c("  " + txt, "bold"))
    print(c("─" * 64, "gray"))


def ok(txt: str) -> None:
    print("  " + c("✓ ", "green") + txt)


def falha(txt: str) -> None:
    print("  " + c("✗ ", "red") + txt)


def aviso(txt: str) -> None:
    print("  " + c("! ", "yellow") + txt)


def passo(txt: str) -> None:
    print("  " + c("→ ", "cyan") + txt)


def perguntar_sim(pergunta: str, default: bool = True) -> bool:
    suf = " [S/n] " if default else " [s/N] "
    try:
        resp = input("  " + c("? ", "yellow") + pergunta + suf).strip().lower()
    except EOFError:
        return default
    if not resp:
        return default
    return resp in ("s", "sim", "y", "yes")


def pausar() -> None:
    try:
        input("\n  " + c("Pressione ENTER para continuar...", "gray"))
    except EOFError:
        pass


# --- Descoberta de comandos ---------------------------------------------------
def _which(nome: str) -> str | None:
    """Localiza um comando no PATH; no Windows tenta também os shims .cmd em %APPDATA%\\npm."""
    p = shutil.which(nome)
    if p:
        return p
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        for cand in (Path(appdata) / "npm" / f"{nome}.cmd",
                     Path(appdata) / "npm" / f"{nome}.exe",
                     Path(appdata) / "npm" / nome):
            if cand.exists():
                return str(cand)
    return None


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Roda um comando mostrando a saída na tela (interativo)."""
    return subprocess.run(cmd, **kw)


def _versao(nome: str) -> str | None:
    exe = _which(nome)
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           timeout=30, creationflags=_NO_WINDOW)
        saida = (r.stdout or r.stderr or "").strip().splitlines()
        return saida[0] if saida else "(instalado)"
    except Exception:  # noqa: BLE001
        return "(instalado)"


# --- Node.js ------------------------------------------------------------------
def verificar_node() -> bool:
    titulo("1/5 · Node.js")
    v = _versao("node")
    if v:
        ok(f"Node.js encontrado: {v}")
        npmv = _versao("npm")
        if npmv:
            ok(f"npm encontrado: {npmv}")
        else:
            aviso("npm não foi encontrado — reinstale o Node.js (o instalador oficial inclui o npm).")
        return bool(npmv)

    falha("Node.js NÃO está instalado. Ele é obrigatório (as CLIs Claude e Codex rodam sobre ele).")
    # Tenta instalação automática via winget (Windows 10/11), se disponível.
    if os.name == "nt" and _which("winget"):
        if perguntar_sim("Quer que eu instale o Node.js automaticamente agora (via winget)?", True):
            passo("Instalando OpenJS.NodeJS.LTS via winget (pode pedir permissão de administrador)...")
            try:
                _run(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                      "--accept-source-agreements", "--accept-package-agreements"])
            except Exception as e:  # noqa: BLE001
                falha(f"Falha ao chamar o winget: {e}")
            aviso("Feche e reabra este Setup para o PATH atualizar e o Node ser reconhecido.")
            return False

    aviso("Instale o Node.js manualmente (versão LTS):")
    passo(f"Abrindo a página de download: {NODE_URL}")
    try:
        webbrowser.open(NODE_URL)
    except Exception:  # noqa: BLE001
        pass
    passo("Baixe o instalador 'LTS' para Windows, execute-o e mantenha todas as opções padrão.")
    passo("Depois de instalar, feche e reabra este Setup.")
    return False


# --- CLIs via npm -------------------------------------------------------------
def _instalar_npm(pkg: str) -> bool:
    npm = _which("npm")
    if not npm:
        falha("npm indisponível — instale o Node.js primeiro.")
        return False
    passo(f"Instalando {pkg} globalmente (npm install -g)... isso pode levar 1–2 minutos.")
    try:
        r = _run([npm, "install", "-g", pkg])
        return r.returncode == 0
    except Exception as e:  # noqa: BLE001
        falha(f"Erro ao instalar {pkg}: {e}")
        return False


def verificar_cli(indice: str, comando: str, pkg: str) -> bool:
    titulo(f"{indice} · CLI '{comando}'  ({pkg})")
    if _which(comando):
        ok(f"'{comando}' já está instalado: {_versao(comando)}")
        return True
    falha(f"'{comando}' não encontrado.")
    if perguntar_sim(f"Instalar '{comando}' agora (npm install -g {pkg})?", True):
        if _instalar_npm(pkg):
            if _which(comando):
                ok(f"'{comando}' instalado com sucesso.")
                return True
            aviso("Instalado, mas o comando ainda não aparece no PATH. Feche e reabra o Setup.")
            return False
        falha("Instalação falhou. Comando manual (cole num terminal):")
        print("        " + c(f"npm install -g {pkg}", "cyan"))
    else:
        aviso("Pulei. Para instalar depois, rode num terminal:")
        print("        " + c(f"npm install -g {pkg}", "cyan"))
    return False


# --- Logins -------------------------------------------------------------------
def login_claude() -> None:
    titulo("4/5 · Login do Claude (plano Claude)")
    if not _which("claude"):
        aviso("A CLI 'claude' ainda não está instalada — pule este passo até instalá-la.")
        return
    print("  O Claude Code usa a MESMA conta do seu app Claude. O login abre o navegador.")
    passo("Vou abrir o Claude no modo login. Siga as instruções na tela / no navegador.")
    passo("Se ele já estiver logado, aparecerá o prompt normal — pode fechar com Ctrl+C.")
    if perguntar_sim("Abrir o login do Claude agora?", True):
        exe = _which("claude")
        try:
            # `claude` sem -p entra no modo interativo; use /login lá dentro se pedir.
            _run([exe, "/login"])
        except KeyboardInterrupt:
            pass
        except Exception as e:  # noqa: BLE001
            aviso(f"Não consegui abrir automaticamente ({e}). Rode manualmente:")
            print("        " + c("claude   (e digite /login)", "cyan"))


def login_codex() -> None:
    titulo("5/5 · Login do Codex (plano ChatGPT)")
    if not _which("codex"):
        aviso("A CLI 'codex' ainda não está instalada — pule este passo até instalá-la.")
        return
    print("  O Codex gera as imagens usando a MESMA conta do seu ChatGPT (plano pago).")
    passo("Vou rodar 'codex login' — ele abre o navegador para autorizar.")
    if perguntar_sim("Fazer o login do Codex agora?", True):
        exe = _which("codex")
        try:
            _run([exe, "login"])
        except KeyboardInterrupt:
            pass
        except Exception as e:  # noqa: BLE001
            aviso(f"Não consegui abrir automaticamente ({e}). Rode manualmente:")
            print("        " + c("codex login", "cyan"))
    else:
        aviso("Para logar depois: " + c("codex login", "cyan"))


# --- ffmpeg (opcional) --------------------------------------------------------
def verificar_ffmpeg() -> None:
    titulo("Extra · ffmpeg (opcional — só para o fluxo de VÍDEO)")
    if _which("ffmpeg"):
        ok(f"ffmpeg encontrado: {_versao('ffmpeg')}")
        return
    aviso("ffmpeg não encontrado. Ele só é necessário para gerar VÍDEO (não para imagem).")
    if os.name == "nt" and _which("winget"):
        if perguntar_sim("Instalar o ffmpeg agora (via winget)?", False):
            try:
                _run(["winget", "install", "-e", "--id", "Gyan.FFmpeg",
                      "--accept-source-agreements", "--accept-package-agreements"])
                aviso("Feche e reabra o terminal para o ffmpeg entrar no PATH.")
            except Exception as e:  # noqa: BLE001
                falha(f"Falha no winget: {e}")
            return
    passo("Para instalar depois: " + c("winget install Gyan.FFmpeg", "cyan") +
          "  (ou baixe em https://www.gyan.dev/ffmpeg/builds/)")


# --- Caminhos das CLIs para o app honrar --------------------------------------
def _config_dir() -> Path:
    """Mesma pasta config/ que o app usa (espelha workspace._data_root): ao lado do
    .exe quando congelado; senão a raiz do projeto (packaging/ fica um nível abaixo)."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "config"


def gravar_cli_paths() -> None:
    """Grava config/cli_paths.env com os caminhos ABSOLUTOS das CLIs, para o app
    honrar (o workspace prepende esses diretórios ao PATH em runtime). Mesmo formato
    do first_run_mac (NODE_PATH=..., CLAUDE_PATH=..., etc.): quem instala Node via
    nvm-windows/prefixo npm custom não fica no PATH que o app enxerga sozinho."""
    linhas = [
        "# Caminhos ABSOLUTOS detectados pelo Setup. O app adiciona estes",
        "# diretórios ao PATH em runtime (nvm-windows/prefixo npm custom não entram sozinhos).",
    ]
    for tool in ("node", "npm", "claude", "codex", "ffmpeg"):
        p = _which(tool)
        if p:
            linhas.append(f"{tool.upper()}_PATH={p}")
    try:
        cfg = _config_dir()
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "cli_paths.env").write_text("\n".join(linhas) + "\n", encoding="utf-8")
        ok(f"Caminhos das ferramentas salvos para o app: {cfg / 'cli_paths.env'}")
    except Exception as e:  # noqa: BLE001
        aviso(f"Não consegui gravar o cli_paths.env ({e}).")


# --- Resumo -------------------------------------------------------------------
def resumo() -> None:
    titulo("Resumo")
    itens = [
        ("Node.js", bool(_which("node"))),
        ("CLI claude", bool(_which("claude"))),
        ("CLI codex", bool(_which("codex"))),
        ("ffmpeg (vídeo, opcional)", bool(_which("ffmpeg"))),
    ]
    for nome, presente in itens:
        (ok if presente else aviso)(nome + (": pronto" if presente else ": pendente"))
    essenciais_ok = all(_which(x) for x in ("node", "claude", "codex"))
    print()
    if essenciais_ok:
        print(c("  Tudo pronto! Você já pode abrir o Ads Express e gerar criativos.", "green"))
    else:
        print(c("  Faltam itens essenciais acima. Rode o Setup de novo depois de resolvê-los.", "yellow"))


def deps_essenciais_ok() -> bool:
    """Usado pelo app para decidir se precisa sugerir o Setup na primeira execução."""
    return all(_which(x) for x in ("node", "claude", "codex"))


def main() -> int:
    _enable_ansi()
    print(c("\n  ╔══════════════════════════════════════════════════════════╗", "cyan"))
    print(c("  ║   Ads Express · Setup / Reparar                          ║", "cyan"))
    print(c("  ╚══════════════════════════════════════════════════════════╝", "cyan"))
    print("  Este assistente prepara o que o app precisa para funcionar.")
    print(c("  Pode rodar quantas vezes quiser — ele não estraga nada já instalado.", "gray"))

    node_ok = verificar_node()
    if node_ok:
        verificar_cli("2/5", "claude", CLAUDE_PKG)
        verificar_cli("3/5", "codex", CODEX_PKG)
        login_claude()
        login_codex()
    else:
        aviso("Sem Node.js não dá para instalar as CLIs. Resolva o passo 1 e rode o Setup de novo.")
    verificar_ffmpeg()
    gravar_cli_paths()
    resumo()
    pausar()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Setup interrompido.")
        sys.exit(1)
