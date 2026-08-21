"""Catálogo, storage e loader de cérebro por FORMATO de vídeo UGC.

Modo PARALELO ao fluxo atual: o formato "padrao" mantém exatamente o comportamento
de hoje (cérebros copy_ugc.md / roteirista_ugc.md). Cada formato novo pode ter um
cérebro de roteirista dedicado em app/prompts/video_formatos/roteirista_<id>.md (e,
opcionalmente, copy_<id>.md). Se o arquivo dedicado não existir, cai no cérebro base
+ uma DIRETIVA curta do formato — então nada quebra enquanto os cérebros são escritos.

A seleção é do PRODUTO e fica em products/<produto>/output/ugc_formatos.json
(lista; o 1º é o formato ATIVO do lote atual)."""
from __future__ import annotations

from pathlib import Path

from workspace import atomic_write_json, ler_json, product_dir

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "app" / "prompts"
FMT_DIR = PROMPTS / "video_formatos"

# id, label, desc (curta, do próprio produto), multi_pessoa (elenco > 1 permitido)
CATALOGO = [
    ("padrao", "Padrão (UGC)",
     "Uma pessoa falando pra câmera em tom de depoimento/UGC (o modo de sempre).", False),
    ("nativo", "Nativo (orgânico)",
     "Conteúdo nativo camuflado: entrega valor primeiro e o produto entra depois, sem cara de anúncio.", False),
    ("fala_faz", "Fala e Faz",
     "A pessoa fala a mensagem enquanto FAZ uma ação visualmente interessante (arrumar a casa, fazer um café). A ação secundária prende o olhar.", False),
    ("depoimento", "Depoimento",
     "Cliente conta a experiência. Estrutura: como era a vida antes, o que mudou com o produto, o resultado. Foco em prova social e quebra de objeção.", False),
    ("experimento_social", "Experimento Social",
     "Um teste/experimento em público ou na prática pra provar um ponto. Gera curiosidade e prova o valor de um jeito inegável.", True),
    ("esquete", "Esquete",
     "Cena curta e engraçada que exagera a dor do público. O ponto alto é o produto entrar como o herói que salva o dia. Humor é a arma.", True),
    ("telepatia", "Telepatia",
     "Você 'adivinha' o que o público pensa (dor, objeção, desejo). Abre com 'Eu sei o que você tá pensando...' ou 'Cansado de...'. Conexão imediata.", False),
    ("palestrinha", "Palestrinha",
     "Tom de autoridade, mini-aula sobre um tema. Educa sobre o problema, quebra crenças limitantes e posiciona o produto como solução definitiva.", False),
    ("corte_podcast", "Corte de Podcast",
     "Simula um trecho de podcast: UM especialista falando (host implícito fora do quadro). No meio do papo, o produto entra como solução/exemplo. Transmite autoridade e profundidade.", False),
    ("lofi", "Lo-fi",
     "Estética relax (low fidelity), cores mais apagadas, trilha calma, clima de reflexão. Mostra o produto de um jeito artístico e menos agressivo.", False),
    ("top5", "Top 5 (ranking)",
     "Lista numerada (Top 3/5) de dicas, erros ou ferramentas. O produto é o item mais importante da lista, ou a lista educa até o CTA final.", False),
    ("conversa_carro", "Conversa no Carro",
     "Você se filma dentro do carro, como um desabafo/reflexão. A informalidade cria intimidade e sensação de pensamento sincero e espontâneo.", False),
    ("dialogo", "Diálogo",
     "Dois pontos de vista batendo papo (você e um amigo, ou o mesmo você antes/depois). Levanta dúvidas e quebra objeções de forma natural. Sem truque de gêmeos: usar corte alternado (shot-reverse).", True),
    ("passo_a_passo", "Passo a passo",
     "Tutorial rápido que ensina a fazer algo. O produto é a ferramenta secreta / a etapa que facilita tudo. Entrega valor na hora.", False),
    ("analogia", "Analogia",
     "Usa uma comparação com algo que todo mundo conhece pra explicar o benefício do produto. Torna o complexo simples e memorável.", False),
    ("receita", "Receita",
     "Simula uma receita de cozinha, mas os 'ingredientes' são os passos pro resultado. O produto é o 'ingrediente secreto' que garante o sucesso.", False),
    ("serie", "Série (dia 1, 2...)",
     "Apresentado como episódio de série ('dia 01 fazendo X'). Termina em cliffhanger que obriga a clicar pra ver a continuação. Cria arco e curiosidade.", False),
    ("rotina", "Rotina",
     "Mostra a rotina (ou parte dela) e o produto entra de forma natural como algo que facilita a vida. Autenticidade e uso no dia a dia.", False),
    ("pov_depoimento", "POV + Depoimento",
     "Começa em POV imersivo (você sente a dor/problema) e corta para um depoimento que valida a dor e apresenta a solução.", False),
    ("certo_errado", "Certo vs Errado",
     "Compara a abordagem 'Errada' (dá tudo errado) com a 'Certa' (usa o produto e dá certo). Didático, mostra o valor pelo contraste.", False),
    ("trivial", "Trivial",
     "Perguntas de curiosidade (trivia) sobre o nicho. O produto é a resposta de uma das perguntas ou a ferramenta que ajuda a acertar tudo.", False),
    ("entrevista", "Entrevista",
     "Você entrevista um especialista (ou cliente) sobre um tema ligado ao produto. O produto é a solução/resultado da conversa. Autoridade e prova social.", True),
    ("pov", "POV",
     "Representa uma cena em primeira pessoa. Imersivo pra mostrar a dor/problema antes de entregar a solução. A pessoa se sente parte da história.", False),
]

_BY_ID = {c[0]: {"id": c[0], "label": c[1], "desc": c[2], "multi_pessoa": c[3]} for c in CATALOGO}
IDS = tuple(c[0] for c in CATALOGO)


def catalogo_publico() -> list[dict]:
    return [{"id": c[0], "label": c[1], "desc": c[2], "multi_pessoa": c[3]} for c in CATALOGO]


def existe(fmt: str) -> bool:
    return fmt in _BY_ID


def info(fmt: str) -> dict:
    return _BY_ID.get(fmt, _BY_ID["padrao"])


def multi_pessoa(fmt: str) -> bool:
    return bool(_BY_ID.get(fmt, {}).get("multi_pessoa"))


# ---- PAPÉIS por formato multi-pessoa ----
# Em formatos com mais de uma pessoa, cada cena traz um "elenco" (A/B). Aqui mapeamos
# QUEM é cada papel e, principalmente, qual elenco carrega a AUTORIDADE — onde um expert
# oficial (influenciador) encaixa como convidado/entrevistado/especialista. O outro papel
# é gerado pelo Veo (entrevistador/apresentador/coadjuvante). Default seguro: A = autoridade.
_PAPEIS = {
    "entrevista":         {"A": "entrevistado/autoridade", "B": "entrevistador", "autoridade": "A"},
    "dialogo":            {"A": "quem defende o ponto/autoridade", "B": "quem questiona", "autoridade": "A"},
    "experimento_social": {"A": "quem conduz o teste/autoridade", "B": "participante", "autoridade": "A"},
    "esquete":            {"A": "protagonista/autoridade", "B": "coadjuvante", "autoridade": "A"},
}


def papel_autoridade(fmt: str) -> str:
    """Elenco (A/B) que carrega a AUTORIDADE no formato multi-pessoa (onde um expert
    oficial entra). Default seguro 'A' pra qualquer multi sem mapeamento explícito."""
    return (_PAPEIS.get(fmt) or {}).get("autoridade", "A")


# Formatos TWO-SHOT: as DUAS pessoas aparecem no MESMO keyframe (não é corte alternado).
# Ex.: entrevista de rua (repórter + entrevistado juntos) e abordagem de experimento social.
# Só um fala/lipsync por clipe; o outro reage. Requer suporte no keyframes.py (montar_prompt
# descreve os dois; ancoragem trata a dupla como um personagem "AB").
_TWO_SHOT = {"entrevista", "experimento_social"}


def two_shot(fmt: str) -> bool:
    """Se o formato mostra as DUAS pessoas juntas no mesmo keyframe (two-shot)."""
    return fmt in _TWO_SHOT


def papeis(fmt: str) -> dict:
    """Descrição dos papéis A/B do formato multi (dict vazio nos formatos solo)."""
    return dict(_PAPEIS.get(fmt) or {})


# ---- storage por produto ----
def _path(produto: str) -> Path:
    return product_dir(produto) / "output" / "ugc_formatos.json"


def ler_formatos(produto: str) -> list[str]:
    dados = ler_json(_path(produto)) or {}
    fs = [x for x in (dados.get("formatos") or []) if x in _BY_ID]
    # dedup preservando ordem
    out, vistos = [], set()
    for x in fs:
        if x not in vistos:
            vistos.add(x); out.append(x)
    return out or ["padrao"]


def escrever_formatos(produto: str, formatos: list[str]) -> list[str]:
    fs = [x for x in formatos if x in _BY_ID] or ["padrao"]
    out, vistos = [], set()
    for x in fs:
        if x not in vistos:
            vistos.add(x); out.append(x)
    p = _path(produto)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, {"formatos": out})
    return out


def formato_ativo(produto: str) -> str:
    return ler_formatos(produto)[0]


# padrao/nativo são os dois "modos base" (viram o `modo` UGC vs Nativo do cérebro base).
_MODO_BASE = {"padrao": "ugc_depoimento", "nativo": "organico_camuflado"}


def modo_do_formato(fmt: str) -> str:
    """Deriva o `modo` (UGC x Nativo) do formato escolhido. Padrão=UGC, Nativo=orgânico,
    demais formatos=UGC por padrão (a estrutura vem do próprio formato)."""
    return _MODO_BASE.get(fmt, "ugc_depoimento")


def distribuir(n: int, formatos: list[str]) -> list[str]:
    """Distribui N itens entre os formatos marcados (round-robin i % M).
    N<M -> os primeiros N formatos (um cada); N=M -> um de cada; N>M -> equilibrado.
    Ex.: distribuir(5, [padrao,wikihow,noticia]) = [padrao,wikihow,noticia,padrao,wikihow]."""
    fs = [f for f in formatos if f in _BY_ID] or ["padrao"]
    n = max(1, int(n or 1))
    return [fs[i % len(fs)] for i in range(n)]


# ---- cérebros por formato (bespoke se existir, senão base) ----
def _ler(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


# O cérebro de um formato = CONTRATO TÉCNICO base (schema roteiro-json, tipos de
# cena, regras da esteira) + ADENDO do formato (estrutura/copy/visual específicos).
# O adendo vem POR ÚLTIMO, então sobrepõe o base onde precisar. Sem adendo, usa só o base.
def roteirista_cerebro(fmt: str) -> str:
    base = _ler(PROMPTS / "roteirista_ugc.md")
    if fmt == "padrao":
        return base
    add = _ler(FMT_DIR / f"roteirista_{fmt}.md")
    if not add:
        return base
    return (base + "\n\n\n===== ADENDO DO FORMATO (SOBREPÕE O ACIMA ONDE HOUVER CONFLITO) =====\n"
            + add)


def copy_cerebro(fmt: str) -> str:
    base = _ler(PROMPTS / "copy_ugc.md")
    if fmt == "padrao":
        return base
    add = _ler(FMT_DIR / f"copy_{fmt}.md")
    if not add:
        return base
    return (base + "\n\n\n===== ADENDO DO FORMATO (SOBREPÕE O ACIMA ONDE HOUVER CONFLITO) =====\n"
            + add)


def diretiva(fmt: str) -> str:
    """Bloco curto injetado na mensagem reforçando o formato escolhido (vale mesmo
    quando o cérebro é o base). Vazio pros modos base (padrão/nativo)."""
    if fmt in ("padrao", "nativo") or fmt not in _BY_ID:
        return ""
    i = _BY_ID[fmt]
    extra = ""
    if fmt in _TWO_SHOT:
        extra = (" ELENCO (TWO-SHOT): este formato mostra AS DUAS pessoas JUNTAS no mesmo quadro, interagindo "
                 "(não é corte alternado). Em cada cena, o campo `elenco` marca QUEM FALA (A ou B); a outra "
                 "pessoa aparece ao lado reagindo. Descreva SEMPRE as duas no `prompt_keyframe`, distintas "
                 "entre si (visual/tom), e só uma falando por cena. LOCAÇÃO: é uma ABORDAGEM DE RUA — calçada/"
                 "praça movimentada, gente passando ao fundo, luz natural de dia, o repórter (elenco B) segura "
                 "um MICROFONE DE MÃO estendido pro entrevistado. NÃO é estúdio, sofá, sala nem mesa de podcast.")
    elif i["multi_pessoa"]:
        extra = (" ELENCO: este formato pode ter MAIS DE UMA pessoa. Estruture como corte alternado "
                 "(shot-reverse): cada cena mostra UMA pessoa por vez (nunca duas no mesmo keyframe), "
                 "alternando entre os interlocutores. A segunda pessoa é distinta da primeira (outro visual/tom).")
    return (f"\n\n## FORMATO DE VÍDEO ESCOLHIDO: {i['label']}\n{i['desc']}\n"
            f"Todo o roteiro deve encarnar ESTE formato do começo ao fim (não o UGC genérico).{extra}\n")
