"""Ponte de TEXTO via Codex CLI (plano ChatGPT — custo de API = zero).

Alternativa ao `claude_bridge` para gerar copies/prompts com um modelo GPT-5, dando ao
usuário a opção de testar GPT vs Claude no dropdown. Usa `codex exec` com:
- `--model` GERAL (gpt-5.5, o mais amplo — não é o de coding puro);
- `--sandbox read-only` → o Codex NÃO mexe em arquivo nenhum (não age como agente-dev);
- `--ephemeral` → não persiste sessão em disco;
- `-o <arquivo>` → grava SÓ a resposta final limpa (sem o transcript do agente).

Como o modo ephemeral não mantém continuidade, o multi-turno é resolvido aqui: guardamos o
histórico por sessão e reenviamos o contexto a cada mensagem.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from backends.codex_backend import _NO_WINDOW, _codex_cmd_base, _kill_tree

# Aliases do dropdown -> modelo real do Codex (todos são GPT-5 pelo plano).
MODELOS = {
    "gpt5": "gpt-5.6-terra",
    "gpt": "gpt-5.6-terra",
    "gpt-5.5": "gpt-5.5",
    "gpt-5.6-sol": "gpt-5.6-sol",
}
MODELO_PADRAO = "gpt-5.6-terra"

# Cache de modelos que o próprio Codex CLI mantém atualizado.
_MODELS_CACHE = Path.home() / ".codex" / "models_cache.json"

# Papéis por consumo de cota -> como reconhecer o modelo na descrição do cache.
# Assim, quando sair a geração 5.7, o slot certo passa a apontar pro novo sozinho.
_PAPEIS = [
    ("alto", lambda d: "frontier" in d),
    ("medio", lambda d: "balanced" in d or "everyday" in d),
    ("baixo", lambda d: "fast" in d and "affordable" in d),
]
# Fallback fixo caso o cache suma ou mude de formato (não quebra o dropdown).
_GPT_FALLBACK = [
    ("baixo", "gpt-5.6-luna", "GPT-5.6 Luna"),
    ("medio", "gpt-5.6-terra", "GPT-5.6 Terra"),
    ("alto", "gpt-5.6-sol", "GPT-5.6 Sol"),
]


def _versao(slug: str) -> tuple:
    """(maior, menor) da versão no slug, p/ escolher o mais novo. gpt-5.6-x -> (5,6)."""
    m = re.search(r"(\d+)\.(\d+)", slug or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def modelos_disponiveis() -> list[dict]:
    """Lê o models_cache.json do Codex e devolve UM GPT por consumo (baixo/médio/alto).

    Cada item: {id, label, consumo}. Escolhe, por papel, o modelo mais NOVO cuja
    descrição bate com o papel — segue novas gerações sem editar código.
    """
    try:
        dados = json.loads(_MODELS_CACHE.read_text(encoding="utf-8"))
        modelos = [m for m in dados.get("models", []) if m.get("visibility") == "list"]
    except Exception:  # noqa: BLE001
        modelos = []

    saida: list[dict] = []
    if modelos:
        for consumo, casa in _PAPEIS:
            candidatos = [m for m in modelos if casa((m.get("description") or "").lower())]
            if not candidatos:
                continue
            melhor = max(candidatos, key=lambda m: _versao(m.get("slug", "")))
            saida.append({
                "id": melhor["slug"],
                "label": melhor.get("display_name") or melhor["slug"],
                "consumo": consumo,
            })
    if not saida:  # cache indisponível: usa o fallback fixo
        saida = [{"id": s, "label": lbl, "consumo": c} for c, s, lbl in _GPT_FALLBACK]
    # Ordena baixo -> médio -> alto pra ficar coerente com o Claude no dropdown.
    ordem = {"baixo": 0, "medio": 1, "alto": 2}
    saida.sort(key=lambda x: ordem.get(x["consumo"], 9))
    return saida

# Histórico por sessão (ephemeral não tem --resume, então mantemos o contexto aqui).
_SESSOES: dict[str, list[tuple[str, str]]] = {}


def _modelo(alias) -> str:
    if not alias:
        return MODELO_PADRAO
    a = str(alias).lower()
    if a in MODELOS:
        return MODELOS[a]
    if a.startswith("gpt-"):   # slug exato vindo do dropdown (ex.: gpt-5.6-terra)
        return a
    return MODELO_PADRAO


def _run_codex_text(prompt: str, modelo, timeout: int) -> str:
    """Roda `codex exec` e devolve só a última mensagem do agente (texto limpo)."""
    last_f = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".last",
                                         encoding="utf-8", errors="replace")
    last_path = last_f.name
    last_f.close()
    in_f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".in",
                                       encoding="utf-8", errors="replace")
    in_f.write(prompt)
    in_f.close()
    err_f = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".err",
                                        encoding="utf-8", errors="replace")
    err_path = err_f.name
    err_f.close()

    cmd = _codex_cmd_base() + [
        "exec",
        "--model", _modelo(modelo),
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "-o", last_path,
        "-",  # prompt via stdin
    ]

    timed_out = False
    stdin_h = open(in_f.name, "r", encoding="utf-8")
    errh = open(err_path, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(cmd, stdin=stdin_h, stdout=subprocess.DEVNULL,
                                stderr=errh, text=True, creationflags=_NO_WINDOW)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc.pid)
    finally:
        stdin_h.close()
        errh.close()

    resposta = Path(last_path).read_text(encoding="utf-8", errors="replace").strip()
    erro = Path(err_path).read_text(encoding="utf-8", errors="replace")
    for p in (last_path, in_f.name, err_path):
        try:
            os.unlink(p)
        except OSError:
            pass

    if timed_out:
        raise RuntimeError("Codex (GPT) demorou demais e foi encerrado (timeout).")
    if not resposta:
        raise RuntimeError(f"Codex (GPT) não retornou texto. stderr: {erro[-500:]}")
    return resposta


def conversar(mensagem: str, session_id: str | None = None, modelo: str | None = None,
              system_prompt: str | None = None, cwd: str | None = None,
              timeout: int = 300, add_dirs: list | None = None) -> dict:
    """Mesma assinatura do claude_bridge.conversar. Multi-turno via histórico local.

    add_dirs é aceito por compatibilidade com o claude_bridge, mas ignorado: o Codex
    roda em sandbox read-only e não lê imagens anexadas do chat de copy.
    """
    sid = session_id if (session_id and session_id in _SESSOES) else ("gpt_" + uuid.uuid4().hex[:12])
    hist = _SESSOES.setdefault(sid, [])

    partes: list[str] = []
    if system_prompt:
        partes.append(system_prompt.strip())
    for role, txt in hist:
        rot = "Usuário" if role == "user" else "Você (copywriter)"
        partes.append(f"{rot}:\n{txt}")
    partes.append(f"Usuário:\n{mensagem}")
    if hist:
        partes.append("Continue como a próxima resposta do copywriter, mantendo TODAS as "
                      "copies vigentes e terminando com o bloco copies-json completo.")

    resposta = _run_codex_text("\n\n".join(partes), modelo, timeout)
    hist.append(("user", mensagem))
    hist.append(("assistant", resposta))
    return {"resposta": resposta, "session_id": sid}


def pedir_texto(prompt: str, modelo: str | None = None, system_prompt: str | None = None,
                cwd: str | None = None, timeout: int = 300, add_dirs: list | None = None) -> str:
    """One-shot (usado na geração de prompts de imagem). add_dirs ignorado (ver conversar)."""
    partes = []
    if system_prompt:
        partes.append(system_prompt.strip())
    partes.append(prompt)
    return _run_codex_text("\n\n".join(partes), modelo, timeout)
