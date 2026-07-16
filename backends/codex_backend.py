"""Backend de geração via Codex CLI (consome o plano ChatGPT — custo de API = zero).

Como funciona:
- Dispara `codex exec` de forma não-interativa, passando o prompt e as fotos de
  referência com `-i`. IMPORTANTE: o prompt vem ANTES dos `-i` porque a flag `-i`
  é variádica e engoliria o texto do prompt.
- O Codex salva o PNG em ~/.codex/generated_images/<sessao>/exec-<uuid>.png e o
  sandbox impede que ele copie pro destino final — então nós pegamos o PNG mais
  recente dessa pasta e copiamos para `output_path`.

Pré-requisito: `codex login` feito (verifique com `codex login status`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

GENERATED_DIR = Path.home() / ".codex" / "generated_images"


def _run_codex(cmd: list[str], timeout: int, cwd: str | None):
    """Roda o Codex de forma robusta no Windows.

    - stdin fechado (o Codex nunca fica esperando input).
    - stdout/stderr vão para arquivos temporários (evita o deadlock clássico de
      pipe quando o processo-neto codex.exe herda os handles e não os fecha).
    - no timeout, mata a ÁRVORE de processos (node.exe + codex.exe), não só o pai.
    Retorna (stdout, stderr, timed_out).
    """
    out_f = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".out", encoding="utf-8", errors="replace")
    err_f = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".err", encoding="utf-8", errors="replace")
    out_path, err_path = out_f.name, err_f.name
    timed_out = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=out_f,
            stderr=err_f,
            cwd=cwd,
            text=True,
        )
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc.pid)
    finally:
        out_f.close()
        err_f.close()
    stdout = Path(out_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(err_path).read_text(encoding="utf-8", errors="replace")
    for p in (out_path, err_path):
        try:
            os.unlink(p)
        except OSError:
            pass
    return stdout, stderr, timed_out


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _codex_cmd_base() -> list[str]:
    """Comando base para invocar o Codex.

    No Windows, `codex` é um shim `codex.CMD` que passa pelo cmd.exe e quebra
    caminhos com espaço. Por isso, quando possível, chamamos `node codex.js`
    diretamente (node.exe é um executável real e o Python faz o quoting certo).
    """
    node = shutil.which("node")
    candidatos = []
    exe = shutil.which("codex")
    if exe:
        # .../npm/codex.CMD -> .../npm/node_modules/@openai/codex/bin/codex.js
        candidatos.append(Path(exe).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js")
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidatos.append(Path(appdata) / "npm" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js")

    if node:
        for js in candidatos:
            if js.exists():
                return [node, str(js)]

    # Fallbacks: binário nativo, ou o próprio shim (pode ter problema com espaços).
    if exe:
        return [exe]
    return ["codex"]


def _snapshot_pngs() -> dict[Path, float]:
    if not GENERATED_DIR.exists():
        return {}
    return {p: p.stat().st_mtime for p in GENERATED_DIR.rglob("*.png")}


def generate(
    prompt: str,
    reference_paths: list,
    output_path,
    size: str = "1024x1024",
    timeout: int = 300,
    workdir: str | None = None,
    **_ignored,
) -> str:
    """Gera 1 imagem e a salva em output_path. Levanta exceção em caso de falha."""
    output_path = Path(output_path)

    instruction = (
        "Gere UMA imagem usando $imagegen. Use a(s) imagem(ns) de referência anexada(s) "
        "como referência FIEL e OBRIGATÓRIA do produto — o produto no resultado deve ser "
        "idêntico ao das referências. Não explique nem descreva: apenas gere a imagem.\n\n"
        f"{prompt}"
    )

    cmd = _codex_cmd_base() + [
        "exec",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        instruction,
    ]
    for ref in reference_paths:
        cmd += ["-i", str(ref)]

    before = _snapshot_pngs()
    start = time.time()

    stdout, stderr, timed_out = _run_codex(cmd, timeout=timeout, cwd=workdir)

    after = _snapshot_pngs()
    # Imagens que não existiam antes, ou que foram (re)geradas depois do início.
    novos = [p for p, m in after.items() if p not in before or m > start]
    if not novos:
        novos = [p for p, m in after.items() if m >= start - 2]
    if not novos:
        motivo = "Timeout: o Codex demorou demais e foi encerrado." if timed_out else "Codex não gerou nenhuma imagem."
        raise RuntimeError(
            f"{motivo}\n"
            f"stdout (fim):\n{(stdout or '')[-1500:]}\n"
            f"stderr (fim):\n{(stderr or '')[-800:]}"
        )

    mais_novo = max(novos, key=lambda p: p.stat().st_mtime)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(mais_novo, output_path)
    return str(output_path)
