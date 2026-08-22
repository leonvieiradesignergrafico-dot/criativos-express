"""Etapa 1: copy -> roteiro UGC estruturado (roteiro.json), via claude bridge."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from workspace import atomic_write_json, ler_json, pessoa_dir, product_dir, tipo_produto, video_dir
from app.pipeline import formatos_video as fv

ROOT = Path(__file__).resolve().parent.parent.parent
CEREBRO = (ROOT / "app" / "prompts" / "roteirista_ugc.md").read_text(encoding="utf-8")

# Id do vídeo: o strftime tem resolução de 1 SEGUNDO, então N roteiros do MESMO produto
# criados em paralelo (ao mesmo segundo) colidiam no mesmo diretório e um sobrescrevia o
# outro. Um contador protegido por lock garante unicidade thread-safe dentro do processo;
# o sufixo aleatório desambigua entre processos (app + eventual worker).
_VID_LOCK = threading.Lock()
_VID_SEQ = 0


def _novo_vid() -> str:
    """Gera um id de vídeo único e seguro para chamadas concorrentes."""
    global _VID_SEQ
    with _VID_LOCK:
        _VID_SEQ = (_VID_SEQ + 1) % 100000
        seq = _VID_SEQ
    return time.strftime("ugc_%Y%m%d_%H%M%S") + f"_{seq:05d}_{uuid.uuid4().hex[:6]}"

_RE_BLOCO = re.compile(r"```roteiro-json\s*(.*?)```", re.DOTALL)

# Regra do projeto: PROIBIDO travessão/hífen de pontuação na copy. A narração vira
# áudio (Veo) e legenda queimada, então limpamos aqui como no fluxo de imagem.
_RE_TRAVESSAO = re.compile(r"[ \t]*[—–][ \t]*")
_RE_HIFEN_PONT = re.compile(r"[ \t]+-[ \t]+")


def _limpa_narracao(s: str) -> str:
    if not isinstance(s, str) or not s:
        return s
    t = _RE_TRAVESSAO.sub(", ", s)
    t = _RE_HIFEN_PONT.sub(", ", t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",\s*,+", ",", t)
    return t.strip()

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


def contexto_pessoa(nome: str | None, pessoa_tipo: str = "avatar", tipo_prod: str = "fisico",
                    elenco_gerado: bool = False, multi: bool = False) -> str:
    if not nome:
        if elenco_gerado:
            # Multi-pessoa sem avatar de casa: o elenco é GERADO pelo Veo, coerente com o
            # cenário/formato. Não descrever avatar específico; usar corte alternado A/B.
            return ("ELENCO GERADO: este vídeo NÃO usa avatar de casa. As pessoas da cena são "
                    "GERADAS, coerentes com o cenário e o formato (corte alternado entre os papéis "
                    "A e B, UMA pessoa por cena, nunca as duas no mesmo quadro). Marque cada cena com "
                    "elenco A ou B conforme o papel. Não descreva um avatar fixo; deixe o visual das "
                    "pessoas a cargo do formato.")
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
    if multi:
        # Formato multi-pessoa: a pessoa selecionada é a AUTORIDADE recorrente (papel A);
        # o segundo interlocutor (papel B) é OUTRA pessoa, gerada pelo Veo.
        regra = ("\n\nREGRA DE IDENTIDADE (formato multi-pessoa): a pessoa selecionada acima é a "
                 "AUTORIDADE recorrente (papel A: entrevistado/convidado/especialista) e aparece "
                 "IDÊNTICA nas cenas de elenco A. O formato PODE ter um segundo interlocutor "
                 "(papel B: entrevistador/apresentador), que é OUTRA pessoa (não a autoridade). "
                 "Marque cada cena com elenco A ou B; nunca coloque as duas no mesmo quadro (corte "
                 "alternado). Não troque a autoridade por outra pessoa nas cenas A.")
    else:
        regra = ("\n\nREGRA DE IDENTIDADE: somente a pessoa selecionada acima pode aparecer. "
                 "Não introduza outro nome próprio, não troque a pessoa e não crie uma segunda pessoa. "
                 "Se a copy mencionar outro nome, trate-o como texto/placeholder e substitua por "
                 "'a pessoa selecionada'.")
    return papel + txt + regra


def extrair_cenas(resposta: str, digital: bool = False, multi_pessoa: bool = True) -> list | None:
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
        elenco = str(c.get("elenco") or "A").strip().upper()
        # Só formatos multi-pessoa (diálogo/entrevista/esquete) podem usar o 2º
        # interlocutor. Nos demais, um "B" espúrio do modelo vira "A".
        if elenco not in ("A", "B") or not multi_pessoa:
            elenco = "A"
        limpas.append({
            "n": int(c.get("n") or i),
            "tipo": tipo,
            "elenco": elenco,
            "duracao_s": int(c.get("duracao_s") or 5),
            "narracao": _limpa_narracao(str(c.get("narracao") or "").strip()),
            "prompt_keyframe": str(c.get("prompt_keyframe") or "").strip(),
            "prompt_movimento": str(c.get("prompt_movimento") or "").strip(),
            "geometria": c.get("geometria") if isinstance(c.get("geometria"), dict) else {},
            "keyframe": {"arquivo": None, "aprovado": False, "tentativas": 0},
            "audio": {"arquivo": None, "duracao_s": None},
            "clipe": {"arquivo": None, "gerado": False, "fal_request_id": None,
                      "erro": None, "lipsync_aplicado": False},
            "qualidade": {"estado": "pendente", "etapa": None, "tentativa": 0,
                           "motivos": [], "descartes": 0},
            # Insert (B-roll/motion graphics) OPCIONAL: substitui só o VÍDEO desta cena na
            # montagem final, mantendo o ÁUDIO original (voz) intacto por baixo. Gerado em 2
            # passos, como o keyframe: imagem estática aprovada -> animada via Veo i2v (mudo).
            "insert": {
                "ativo": False,
                "conceito": "", "prompt_imagem": "", "prompt_movimento": "",
                "imagem": {"arquivo": None, "aprovado": False, "tentativas": 0},
                "clipe": {"arquivo": None, "gerado": False, "erro": None},
            },
        })
    return limpas


def _mesclar_cenas(antigas: list, novas: list) -> list:
    """Preserva keyframe/áudio/clipe/insert de cenas que NÃO mudaram (mesmo n e prompts)."""
    por_n = {c["n"]: c for c in (antigas or [])}
    out = []
    for c in novas:
        velha = por_n.get(c["n"])
        if velha and velha.get("prompt_keyframe") == c["prompt_keyframe"] \
                and velha.get("narracao") == c["narracao"] \
                and velha.get("prompt_movimento") == c.get("prompt_movimento") \
                and velha.get("elenco", "A") == c.get("elenco", "A") \
                and velha.get("tipo") == c.get("tipo"):
            c["keyframe"], c["audio"], c["clipe"] = velha["keyframe"], velha["audio"], velha["clipe"]
            if velha.get("insert"):
                c["insert"] = velha["insert"]
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
                  formato_video: str = "ugc_depoimento", elenco_gerado: bool = False) -> dict:
    """Gera o roteiro inicial e cria videos/<produto>/<vid>/roteiro.json.

    Casting (novo): `avatar`/`pessoa_tipo` guardam a pessoa recorrente resolvida (avatar UGC
    ou expert); `elenco_gerado=True` marca os vídeos multi-pessoa cujo elenco é GERADO pelo
    Veo (sem referência de avatar de casa). O keyframes usa esses campos + o `elenco` de cada
    cena pra decidir quando anexar (ou não) a foto de referência."""
    vid = _novo_vid()
    tipo_prod = tipo_produto(produto)
    # Formato de vídeo escolhido: troca o cérebro do roteirista e injeta a diretiva.
    # Se formato_video for um id conhecido (fala_faz, top5, ...) usa o cérebro dedicado;
    # senão (legado "ugc_depoimento"/"organico_camuflado" ou "padrao") usa o base.
    fmt = formato_video if fv.existe(formato_video) else "padrao"
    cerebro = fv.roteirista_cerebro(fmt)
    mensagem = (
        f"{contexto_produto(produto)}\n\n{_instrucao_tipo(tipo_prod)}\n\n"
        f"{contexto_pessoa(avatar, pessoa_tipo, tipo_prod, elenco_gerado, fv.multi_pessoa(fmt))}\n\n"
        f"## Formato do vídeo\n{formato_video}{fv.diretiva(fmt)}\n\n"
        f"## Copy aprovada do anúncio\n{copy}\n\n"
        "Crie o roteiro UGC deste anúncio seguindo as regras."
    )
    # O roteiro gera uma saída LONGA (várias cenas, estruturada) — mais que uma resposta
    # de chat. 180s era curto (dava timeout no app empacotado, ainda mais com vários em
    # paralelo). 360s dá folga sem prender o usuário por tempo demais.
    timeout = int((config_video or {}).get("roteiro_timeout", 360))
    r = _bridge(modelo).conversar(mensagem, session_id=None, modelo=modelo,
                                  system_prompt=cerebro, timeout=timeout)
    cenas = extrair_cenas(r["resposta"], digital=(tipo_prod == "digital"),
                          multi_pessoa=fv.multi_pessoa(fmt))
    if not cenas:
        raise RuntimeError("O roteirista não devolveu um bloco roteiro-json válido. "
                           f"Resposta: {r['resposta'][:400]}")
    roteiro = {
        "id": vid,
        "produto": produto,
        "avatar": avatar,
        "pessoa_tipo": pessoa_tipo,
        "elenco_gerado": elenco_gerado,
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
    fmt = roteiro.get("formato_video") or "padrao"
    fmt = fmt if fv.existe(fmt) else "padrao"
    r = _bridge(roteiro.get("modelo")).conversar(
        instrucao, session_id=roteiro.get("session_id"), modelo=roteiro.get("modelo"),
        system_prompt=fv.roteirista_cerebro(fmt), timeout=300)
    _multi = fv.multi_pessoa(fmt)
    roteiro["session_id"] = r.get("session_id") or roteiro.get("session_id")
    roteiro.setdefault("chat", []).append({"papel": "usuario", "texto": instrucao})
    roteiro["chat"].append({"papel": "assistente", "texto": _sem_bloco(r["resposta"])})
    novas = extrair_cenas(r["resposta"], digital=(roteiro.get("tipo_produto") == "digital"),
                          multi_pessoa=_multi)
    if novas:
        roteiro["cenas"] = _mesclar_cenas(roteiro.get("cenas"), novas)
        roteiro["estado"] = "rascunho"
    atomic_write_json(d / "roteiro.json", roteiro)
    return roteiro


def _sem_bloco(texto: str) -> str:
    return _RE_BLOCO.sub("(roteiro atualizado)", texto or "").strip()
