"""Etapa 1: copy -> roteiro UGC estruturado (roteiro.json), via claude bridge."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from workspace import atomic_write_json, ler_json, pessoa_dir, product_dir, tipo_produto, video_dir

ROOT = Path(__file__).resolve().parent.parent.parent
CEREBRO = (ROOT / "app" / "prompts" / "roteirista_ugc.md").read_text(encoding="utf-8")

_RE_BLOCO = re.compile(r"```roteiro-json\s*(.*?)```", re.DOTALL)

# Produto FÍSICO: pessoa segura/veste/mostra o objeto. Produto DIGITAL (infoproduto):
# a pessoa fala sem produto na mão e a entrega é tangibilizada numa TELA de dispositivo.
TIPOS_FISICO = {"close_produto", "avatar_usa", "avatar_mostra", "avatar_fala", "unboxing"}
TIPOS_DIGITAL = {"avatar_fala", "avatar_aponta_tela", "tela_dispositivo", "mockup_resultado"}
TIPOS_VALIDOS = TIPOS_FISICO | TIPOS_DIGITAL
TIPOS_SEM_AVATAR = {"close_produto", "avatar_usa", "unboxing", "tela_dispositivo", "mockup_resultado"}


def _bridge(modelo: str | None):
    if modelo and str(modelo).lower().startswith("gpt"):
        from app import codex_text_bridge as b
    else:
        from app import claude_bridge as b
    return b


def contexto_produto(produto: str) -> str:
    p = product_dir(produto)
    partes = []
    cfg = p / "config.md"
    if cfg.exists():
        partes.append(f"## Produto ({produto})\n" + cfg.read_text(encoding="utf-8", errors="replace"))
    vv = p / "contexto" / "verdade_visual.md"
    if vv.exists():
        partes.append("## Fatos visuais do produto\n" + vv.read_text(encoding="utf-8", errors="replace"))
    refs = p / "referencia"
    if refs.exists() and any(x.is_file() for x in refs.iterdir()):
        partes.append(
            "## Regra visual da interface\n"
            "Ha screenshots/prints do produto anexados em referencia/. Eles sao a fonte unica da verdade "
            "da interface digital: use a mesma tela, layout, cores e textos em todas as cenas. Nao invente "
            "uma UI alternativa nem um dashboard diferente."
        )
    return "\n\n".join(partes) or f"Produto: {produto} (sem config.md)."


def contexto_pessoa(nome: str | None, pessoa_tipo: str = "avatar", tipo_prod: str = "fisico") -> str:
    if not nome:
        if tipo_prod == "digital":
            return ("SEM AVATAR NESTE VÍDEO: não mostre pessoa identificável. Use apenas telas de "
                    "notebook, computador ou celular e mãos neutras quando necessário.")
        return ("SEM AVATAR NESTE VÍDEO: use apenas os tipos de cena close_produto, "
                "avatar_usa (só mãos/corpo, sem rosto) e unboxing.")
    perfil = pessoa_dir(nome, pessoa_tipo) / "perfil.md"
    txt = perfil.read_text(encoding="utf-8", errors="replace") if perfil.exists() else nome
    if pessoa_tipo == "influenciador":
        papel = (f"## Quem aparece: {nome} — INFLUENCIADOR/EXPERT (a própria autoridade da marca)\n"
                 "TOM: não é depoimento de cliente comum; é o expert MOSTRANDO/DEMONSTRANDO com "
                 "autoridade e naturalidade (ainda caseiro/handheld, não corporativo).\n")
    else:
        papel = f"## Avatar do vídeo ({nome}) — pessoa comum, tom de depoimento UGC\n"
    return (papel + txt + "\n\nREGRA DE IDENTIDADE: somente a pessoa selecionada acima pode aparecer. "
            "Não introduza outro nome próprio, não troque a pessoa e não crie uma segunda pessoa. "
            "Se a copy mencionar outro nome, trate-o como texto/placeholder e substitua por 'a pessoa selecionada'.")


def extrair_cenas(resposta: str, digital: bool = False) -> list | None:
    m = None
    for m in _RE_BLOCO.finditer(resposta):
        pass  # fica com o ÚLTIMO bloco (roteiro mais recente da resposta)
    if not m:
        return None
    dado = json.loads(m.group(1))
    cenas = dado.get("cenas") if isinstance(dado, dict) else dado
    if not isinstance(cenas, list) or not cenas:
        return None
    # A esteira foi desenhada para anúncios curtos; impede que uma resposta
    # verbosa do modelo vire 10+ keyframes e trave a produção do vídeo.
    cenas = cenas[:6]
    padrao = "tela_dispositivo" if digital else "close_produto"
    validos = TIPOS_DIGITAL if digital else TIPOS_FISICO
    limpas = []
    for i, c in enumerate(cenas, start=1):
        tipo = str(c.get("tipo") or padrao)
        if tipo not in validos:
            tipo = padrao
        limpas.append({
            "n": int(c.get("n") or i),
            "tipo": tipo,
            "duracao_s": int(c.get("duracao_s") or 5),
            "narracao": str(c.get("narracao") or "").strip(),
            "prompt_keyframe": str(c.get("prompt_keyframe") or "").strip(),
            "prompt_movimento": str(c.get("prompt_movimento") or "").strip(),
            "keyframe": {"arquivo": None, "aprovado": False, "tentativas": 0},
            "audio": {"arquivo": None, "duracao_s": None},
            "clipe": {"arquivo": None, "gerado": False, "fal_request_id": None,
                      "erro": None, "lipsync_aplicado": False},
        })
    return limpas


def _mesclar_cenas(antigas: list, novas: list) -> list:
    """Preserva keyframe/áudio/clipe de cenas que NÃO mudaram (mesmo n e prompts)."""
    por_n = {c["n"]: c for c in (antigas or [])}
    out = []
    for c in novas:
        velha = por_n.get(c["n"])
        if velha and velha.get("prompt_keyframe") == c["prompt_keyframe"] \
                and velha.get("narracao") == c["narracao"] \
                and velha.get("prompt_movimento") == c.get("prompt_movimento"):
            c["keyframe"], c["audio"], c["clipe"] = velha["keyframe"], velha["audio"], velha["clipe"]
        out.append(c)
    return out


def _instrucao_tipo(tipo_prod: str) -> str:
    if tipo_prod == "digital":
        return ("## TIPO DE PRODUTO: DIGITAL (infoproduto)\n"
                "Use SOMENTE os tipos de cena: avatar_fala (pessoa fala SEM produto na mão), "
                "tela_dispositivo (a entrega/interface numa tela de notebook/PC/celular), "
                "avatar_aponta_tela (pessoa + tela, apontando/reagindo), "
                "mockup_resultado (foco no resultado pronto na tela — a prova). "
                "NÃO use unboxing/avatar_usa/avatar_mostra/close_produto (não há objeto físico).")
    return ("## TIPO DE PRODUTO: FÍSICO\n"
            "Use SOMENTE os tipos: close_produto, avatar_usa, avatar_mostra, avatar_fala, unboxing.")


def criar_roteiro(produto: str, copy: str, avatar: str | None, modelo: str | None = None,
                  config_video: dict | None = None, pessoa_tipo: str = "avatar",
                  formato_video: str = "ugc_depoimento") -> dict:
    """Gera o roteiro inicial e cria videos/<produto>/<vid>/roteiro.json."""
    vid = time.strftime("ugc_%Y%m%d_%H%M%S")
    tipo_prod = tipo_produto(produto)
    mensagem = (
        f"{contexto_produto(produto)}\n\n{_instrucao_tipo(tipo_prod)}\n\n"
        f"{contexto_pessoa(avatar, pessoa_tipo, tipo_prod)}\n\n"
        f"## Formato do vídeo\n{formato_video}\n\n"
        f"## Copy aprovada do anúncio\n{copy}\n\n"
        "Crie o roteiro UGC deste anúncio seguindo as regras."
    )
    timeout = int((config_video or {}).get("roteiro_timeout", 180))
    r = _bridge(modelo).conversar(mensagem, session_id=None, modelo=modelo,
                                  system_prompt=CEREBRO, timeout=timeout)
    cenas = extrair_cenas(r["resposta"], digital=(tipo_prod == "digital"))
    if not cenas:
        raise RuntimeError("O roteirista não devolveu um bloco roteiro-json válido. "
                           f"Resposta: {r['resposta'][:400]}")
    roteiro = {
        "id": vid,
        "produto": produto,
        "avatar": avatar,
        "pessoa_tipo": pessoa_tipo,
        "formato_video": formato_video,
        "tipo_produto": tipo_prod,
        "copy_origem": copy,
        "estado": "rascunho",
        "modelo": modelo,
        "session_id": r.get("session_id"),
        "config": config_video or {},
        "chat": [{"papel": "assistente", "texto": _sem_bloco(r["resposta"])}],
        "cenas": cenas,
        "criado": time.time(),
    }
    d = video_dir(produto, vid, create=True)
    atomic_write_json(d / "roteiro.json", roteiro)
    return roteiro


def refinar_roteiro(produto: str, vid: str, instrucao: str) -> dict:
    """Continua a conversa com o roteirista e atualiza as cenas (preservando o que não mudou)."""
    d = video_dir(produto, vid)
    roteiro = ler_json(d / "roteiro.json")
    if not roteiro:
        raise RuntimeError("roteiro.json não encontrado.")
    r = _bridge(roteiro.get("modelo")).conversar(
        instrucao, session_id=roteiro.get("session_id"), modelo=roteiro.get("modelo"),
        system_prompt=CEREBRO, timeout=300)
    roteiro["session_id"] = r.get("session_id") or roteiro.get("session_id")
    roteiro.setdefault("chat", []).append({"papel": "usuario", "texto": instrucao})
    roteiro["chat"].append({"papel": "assistente", "texto": _sem_bloco(r["resposta"])})
    novas = extrair_cenas(r["resposta"], digital=(roteiro.get("tipo_produto") == "digital"))
    if novas:
        roteiro["cenas"] = _mesclar_cenas(roteiro.get("cenas"), novas)
        roteiro["estado"] = "rascunho"
    atomic_write_json(d / "roteiro.json", roteiro)
    return roteiro


def _sem_bloco(texto: str) -> str:
    return _RE_BLOCO.sub("(roteiro atualizado)", texto or "").strip()
