"""Chat de copy/roteiro para o fluxo de vídeo UGC."""
from __future__ import annotations

import json
import re
from pathlib import Path

from workspace import atomic_write_json, product_dir, ler_json, pessoa_dir

ROOT = Path(__file__).resolve().parents[2]
CEREBRO = (ROOT / "app" / "prompts" / "copy_ugc.md").read_text(encoding="utf-8")


def _bridge(modelo: str | None):
    if modelo and str(modelo).lower().startswith("gpt"):
        from app import codex_text_bridge as bridge
    else:
        from app import claude_bridge as bridge
    return bridge


def _chat_path(produto: str) -> Path:
    return product_dir(produto) / "output" / "ugc_copy_chat.json"


def carregar_chat(produto: str) -> dict:
    dados = ler_json(_chat_path(produto)) or {}
    return dados if isinstance(dados, dict) else {}


def _personas() -> str:
    linhas = []
    for pasta, rotulo in ((ROOT / "avatares", "avatar UGC"),
                          (ROOT / "influenciadores", "expert/influenciador oficial")):
        if pasta.exists():
            for d in sorted(pasta.iterdir()):
                perfil = d / "perfil.md"
                if d.is_dir() and perfil.exists():
                    linhas.append(f"- {rotulo} {d.name}: {perfil.read_text(encoding='utf-8', errors='replace')[:500]}")
    return "\n".join(linhas) or "(nenhum avatar UGC cadastrado ainda)"


def _contexto_produto(produto: str, limite: int = 30000) -> str:
    """Contexto comercial real; config sozinho costuma ser rascunho incompleto."""
    p = product_dir(produto)
    candidatos = [p / "config.md", p / "contexto" / "pagina-vendas.txt",
                  p / "contexto" / "aprendizado.md", p / "contexto" / "verdade_visual.md"]
    partes, usados = [], 0
    for f in candidatos:
        if not f.exists() or usados >= limite:
            continue
        txt = f.read_text(encoding="utf-8", errors="replace").strip()
        if not txt:
            continue
        trecho = txt[:limite - usados]
        partes.append(f"## {f.name}\n{trecho}")
        usados += len(trecho)
    return "\n\n".join(partes)


def _extrair(texto: str) -> list[dict]:
    blocos = re.findall(r"```(?:ugc-json|json)?\s*(.*?)```", texto or "", re.S | re.I)
    candidatos = list(reversed(blocos)) + [texto or ""]
    for bruto in candidatos:
        try:
            dado = json.loads(bruto.strip())
        except Exception:
            continue
        if isinstance(dado, dict):
            dado = dado.get("roteiros") or dado.get("opcoes") or dado.get("copies")
        if isinstance(dado, list):
            return [x for x in dado if isinstance(x, dict)]
    return []


def _resumo_resposta(texto: str) -> str:
    """Texto curto para o chat; o bloco JSON fica apenas para o parser interno."""
    limpo = re.sub(r"```(?:ugc-json|json)?\s*.*?```", "", texto or "", flags=re.S | re.I).strip()
    return limpo or "Encontrei algumas opções de roteiro. Escolha uma ou mais abaixo."


def conversar(produto: str, mensagem: str, modelo: str | None, modo: str,
              session_id: str | None = None) -> dict:
    contexto = _contexto_produto(produto)
    pedido = f"""CONTEXTO DO PRODUTO ({produto}):
{contexto or '(sem configuração)'}

PERSONAS/AVATARES DISPONÍVEIS:
{_personas()}

MODO ESCOLHIDO: {modo}

PEDIDO DO USUÁRIO:
{mensagem}

Gere opções de roteiro de vídeo adequadas a este produto, persona, promessa e contexto. Não invente
características, provas, resultados ou ingredientes que não estejam no contexto. Se faltar informação,
faça uma suposição conservadora ou sinalize o ponto no campo observacao.

Não invente nomes próprios para personagens ou personas. O campo persona deve ser descritivo e genérico
(por exemplo, "criador que grava em casa"), nunca "Vini", "Diego" ou outro nome de avatar. O avatar
será escolhido pelo usuário depois; portanto, não amarre nenhuma opção a uma pessoa específica.
"""
    historico = carregar_chat(produto)
    msgs = (historico.get("mensagens") or [])[-30:]
    res = _bridge(modelo).conversar(pedido, session_id=session_id or historico.get("session_id"),
                                    modelo=modelo, system_prompt=CEREBRO, timeout=300)
    opcoes = _extrair(res.get("resposta", ""))
    if not opcoes:
        raise RuntimeError("O roteirista não devolveu opções em formato válido.")
    historico.update({"session_id": res.get("session_id"), "modo": modo})
    historico["mensagens"] = (msgs + [{"papel": "usuario", "texto": mensagem},
                                      {"papel": "assistente", "texto": res.get("resposta", "")}])[-40:]
    atomic_write_json(_chat_path(produto), historico)
    return {"resposta": _resumo_resposta(res.get("resposta", "")), "opcoes": opcoes,
            "session_id": res.get("session_id")}
