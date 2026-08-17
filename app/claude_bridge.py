"""Ponte com o Claude Code em modo headless (`claude -p`).

Consome o SEU PLANO CLAUDE (mesma auth do CLI logado) — custo de API = zero.
Usado para: conversa de copies (multi-turno, com --resume) e geração de prompts de imagem.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

# No Windows, subprocessos de console abrem uma janela CMD quando o pai roda sem
# console (pythonw). Esta flag suprime a janela. Vira 0 em outros SOs.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Aliases amigáveis -> nome de modelo passado ao claude.
MODELOS = {
    "sonnet": "sonnet",
    "opus": "opus",
    "fable": "claude-fable-5",
    "haiku": "haiku",
}

# Versão REAL resolvida por apelido (ex.: "opus" -> "claude-opus-5-..."). Só é
# conhecida DEPOIS de usar o modelo uma vez: o `claude -p --output-format json`
# devolve o id exato em `modelUsage`. Guardamos aqui pro dropdown mostrar.
_RESOLVIDO: dict[str, str] = {}


def modelo_resolvido(alias: str | None) -> str | None:
    """Id exato do modelo que o apelido resolveu na última chamada, se conhecido."""
    if not alias:
        return None
    return _RESOLVIDO.get(str(alias).lower())

# Diretório NEUTRO onde o claude roda: fora do projeto, para NÃO herdar o system
# prompt do Claude Code / CLAUDE.md / skills e não agir como o agente-dev.
NEUTRAL_DIR = Path(tempfile.gettempdir()) / "criativos_express_claude"
NEUTRAL_DIR.mkdir(parents=True, exist_ok=True)


def _claude_exe() -> str:
    """Retorna o claude.exe NATIVO (evita o shim claude.CMD/cmd.exe, que mangla
    prompts multi-linha com caracteres especiais)."""
    import shutil

    shim = shutil.which("claude")
    candidatos = []
    if shim:
        candidatos.append(Path(shim).parent / "node_modules" / "@anthropic-ai"
                          / "claude-code" / "bin" / "claude.exe")
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidatos.append(Path(appdata) / "npm" / "node_modules" / "@anthropic-ai"
                          / "claude-code" / "bin" / "claude.exe")
    for c in candidatos:
        if c.exists():
            return str(c)
    return shim or "claude"


def _run(cmd: list[str], timeout: int, cwd: str | None, stdin_text: str | None = None):
    """Roda um processo de forma robusta (saída em arquivo, tree-kill).

    - O prompt (stdin_text) é enviado via STDIN (arquivo temporário) — evita
      mangling de argv e limites de tamanho de linha de comando no Windows.
    - stdout e stderr são capturados SEPARADAMENTE (misturá-los poluiria o JSON).
    """
    out_f = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".out",
                                        encoding="utf-8", errors="replace")
    err_f = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".err",
                                        encoding="utf-8", errors="replace")
    out_path, err_path = out_f.name, err_f.name

    stdin_path = None
    if stdin_text is not None:
        in_f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".in",
                                           encoding="utf-8", errors="replace")
        in_f.write(stdin_text)
        in_f.close()
        stdin_path = in_f.name
        stdin_handle = open(stdin_path, "r", encoding="utf-8")
    else:
        stdin_handle = subprocess.DEVNULL

    timed_out = False
    try:
        proc = subprocess.Popen(
            cmd, stdin=stdin_handle, stdout=out_f, stderr=err_f, cwd=cwd, text=True,
            creationflags=_NO_WINDOW,
        )
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=_NO_WINDOW)
            else:
                proc.kill()
    finally:
        out_f.close()
        err_f.close()
        if stdin_handle is not subprocess.DEVNULL:
            stdin_handle.close()
    saida = Path(out_path).read_text(encoding="utf-8", errors="replace")
    erro = Path(err_path).read_text(encoding="utf-8", errors="replace")
    for p in (out_path, err_path, stdin_path):
        if p:
            try:
                os.unlink(p)
            except OSError:
                pass
    return saida, erro, timed_out


def _resolver_modelo(modelo: str | None) -> str:
    if not modelo:
        return "sonnet"
    return MODELOS.get(modelo.lower(), modelo)


def conversar(mensagem: str, session_id: str | None = None, modelo: str | None = None,
              system_prompt: str | None = None, cwd: str | None = None,
              timeout: int = 300, add_dirs: list | None = None) -> dict:
    """Envia uma mensagem ao Claude headless e retorna {resposta, session_id}.

    - session_id None -> inicia nova conversa.
    - session_id definido -> continua a conversa (--resume), preservando o contexto.
    - roda em diretório neutro por padrão (não herda o contexto do projeto).
    - add_dirs: pastas extras que o Claude pode LER (ex.: imagens de referência
      anexadas). Sem isso, ler um caminho fora do cwd é negado por permissão.
    """
    # O prompt vai via STDIN (não argv) para evitar mangling/limite de linha de comando.
    cmd = [_claude_exe(), "-p", "--model", _resolver_modelo(modelo),
           "--output-format", "json"]
    if system_prompt:
        cmd += ["--append-system-prompt", system_prompt]
    for d in (add_dirs or []):
        if d:
            cmd += ["--add-dir", str(d)]
    if session_id:
        cmd += ["--resume", session_id]

    saida, erro, timed_out = _run(cmd, timeout=timeout, cwd=cwd or str(NEUTRAL_DIR),
                                  stdin_text=mensagem)
    if timed_out:
        raise RuntimeError("Claude demorou demais e foi encerrado (timeout).")

    # A saída deve ser um JSON com 'result' e 'session_id'.
    try:
        dado = json.loads(saida)
        resposta = dado.get("result") or dado.get("response") or ""
        sid = dado.get("session_id") or session_id
        if dado.get("is_error"):
            raise RuntimeError(resposta or erro or "Erro no Claude.")
        # Captura a versão real que o apelido resolveu (chave de modelUsage).
        mu = dado.get("modelUsage") or {}
        if mu and modelo:
            _RESOLVIDO[str(modelo).lower()] = next(iter(mu.keys()))
        return {"resposta": resposta.strip(), "session_id": sid}
    except json.JSONDecodeError:
        if not saida.strip():
            raise RuntimeError(f"Claude não retornou nada. stderr: {erro[-500:]}")
        # Fallback: se não veio JSON puro, devolve o texto cru.
        return {"resposta": saida.strip(), "session_id": session_id}


def pedir_texto(prompt: str, modelo: str | None = None, system_prompt: str | None = None,
                cwd: str | None = None, timeout: int = 300, add_dirs: list | None = None) -> str:
    """One-shot: manda um prompt e devolve só o texto da resposta."""
    return conversar(prompt, session_id=None, modelo=modelo, system_prompt=system_prompt,
                     cwd=cwd, timeout=timeout, add_dirs=add_dirs)["resposta"]
