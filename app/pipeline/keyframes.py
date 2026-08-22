"""Etapa 2: keyframes GRÁTIS (1 imagem 9:16 por cena) via backend de imagem do irmão."""
from __future__ import annotations

import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from workspace import (VIDEOS, atomic_write_json, carregar_config, ler_json, pessoa_dir,
                       product_dir, tipo_produto, video_dir)
from app.pipeline import formatos_video as fv
from app.pipeline import qualidade
from app.pipeline._status import JobStatus

ROOT = Path(__file__).resolve().parent.parent.parent
PREFIXO_FIDELIDADE = (ROOT / "app" / "prompts" / "diretor_keyframes.md").read_text(encoding="utf-8")
_PREFIXO_DIGITAL_F = ROOT / "app" / "prompts" / "diretor_keyframes_digital.md"
PREFIXO_DIGITAL = (_PREFIXO_DIGITAL_F.read_text(encoding="utf-8")
                   if _PREFIXO_DIGITAL_F.exists() else PREFIXO_FIDELIDADE)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FORMATOS_OK = {".png", ".jpg", ".jpeg", ".webp"}
FORMATOS_CONVERTER = {".avif", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff"}
MAX_IMGS = 5  # limite duro do $imagegen — mais que isso o agente descarta sozinho e viaja
# Cenas em que uma PESSOA aparece de rosto (usa as fotos do avatar/influenciador).
PESSOA_TIPOS = {"avatar_mostra", "avatar_fala", "avatar_usa", "avatar_aponta_tela"}
# Cenas em que a TELA do produto DIGITAL entra no quadro (é o "close" do infoproduto).
# Só nessas a esteira anexa a screenshot do produto — numa cena de fala/pessoa não se
# enfia um laptop (era o "notebook na cara" em podcast/entrevista de produto digital).
TELA_TIPOS = {"tela_dispositivo", "mockup_resultado", "avatar_aponta_tela"}

# O print do infoproduto costuma ser um screenshot de DESKTOP (largo/alto), diferente da
# tela real do aparelho onde ele aparece. Mandado cru, o modelo AGIGANTA/DEFORMA o aparelho
# pra "caber" o conteúdo (celular gigante, notebook com tela esticada/alta demais). A correção
# NÃO é instrução no prompt (o modelo ignora) — é dar a referência JÁ na proporção da tela do
# aparelho ALVO: recortamos o print pra essa proporção antes de anexar. O modelo então desenha
# o aparelho em tamanho e forma NORMAIS. Cada aparelho tem sua proporção de tela (altura/largura):
#   celular retrato ≈ 19,5:9 ; notebook/laptop widescreen ≈ 16:10 ; monitor ≈ 16:9.
_DISPOSITIVOS = {
    "celular": (19.5 / 9.0, "cel", "um CELULAR/smartphone comum em RETRATO, na mão"),
    "laptop":  (10.0 / 16.0, "lap", "um NOTEBOOK/laptop de tela widescreen (16:10), apoiado na mesa"),
    "monitor": (9.0 / 16.0, "mon", "um MONITOR de PC widescreen (16:9) sobre a mesa"),
}
_DISP_LAPTOP_KW = ("notebook", "laptop", "macbook", "computador", "desktop", "monitor", "pc ", "tela do pc")


def _dispositivo_da_cena(cena: dict) -> str:
    """Aparelho onde a tela do produto digital aparece NESTA cena, lido do prompt_keyframe
    (o roteirista descreve). Default: celular (retrato casa com o vídeo 9:16)."""
    txt = (cena.get("prompt_keyframe") or "").lower()
    if any(k in txt for k in _DISP_LAPTOP_KW):
        return "laptop"
    return "celular"


def _adaptar_tela(src: Path, cache: Path, ratio: float, sufixo: str) -> Path:
    """Recorta o print pra proporção da TELA do aparelho alvo (ratio = altura/largura),
    pro modelo desenhar o aparelho em TAMANHO/forma REAIS sem esticar. Âncora no topo
    (mostra o começo da página). Se PIL/leitura falhar, devolve o original — nunca quebra."""
    try:
        from PIL import Image
    except Exception:
        return src
    try:
        cache.mkdir(parents=True, exist_ok=True)
        dst = cache / (src.stem + f"_{sufixo}.png")
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        im = Image.open(src).convert("RGB")
        w, h = im.size
        if w <= 0 or h <= 0:
            return src
        if h / w >= ratio:                       # imagem MAIS ALTA que o alvo -> corta a altura (mantém topo)
            alvo_w, alvo_h = w, max(1, min(h, round(w * ratio)))
            crop = im.crop((0, 0, alvo_w, alvo_h))
        else:                                     # imagem MAIS LARGA/curta -> corta a largura (centraliza)
            alvo_h = h
            alvo_w = max(1, min(w, round(h / ratio)))
            left = max(0, (w - alvo_w) // 2)
            crop = im.crop((left, 0, left + alvo_w, alvo_h))
        crop.save(dst)
        return dst
    except Exception:
        return src

# Paletas de enquadramento pra GARANTIR variação (nunca duas cenas parecidas seguidas). Cada cena
# recebe uma variação por posição dentro do seu grupo — determinístico, não depende do LLM.
_VAR_PESSOA = [
    "PLANO FECHADO: close no rosto/busto, câmera na altura dos olhos, produto entrando de leve no quadro",
    "PLANO MÉDIO: da cintura pra cima, mostrando mais do cômodo ao redor",
    "ÂNGULO LATERAL 3/4: a pessoa levemente de lado (não frontal), olhando pra câmera",
    "PLANO ABERTO: boa parte do corpo e do ambiente de casa aparecem",
    "SELFIE de braço estendido, leve contra-plongée (câmera um pouco de baixo)",
]
_VAR_TELA = [
    "CLOSE na tela do dispositivo (o conteúdo da tela é o herói, nítido)",
    "PLANO MÉDIO: a pessoa e a tela no mesmo quadro, apontando/reagindo",
    "OVER-THE-SHOULDER: por cima do ombro da pessoa, vendo a tela de frente",
]
_VAR_PRODUTO = [
    "CLOSE extremo no produto (textura/detalhe/rótulo)",
    "produto sobre a bancada com o ambiente ao fundo, plano médio",
    "mãos segurando/abrindo o produto, foco nas mãos",
]
_GRUPOS = [
    (PESSOA_TIPOS, _VAR_PESSOA),
    ({"tela_dispositivo", "mockup_resultado"}, _VAR_TELA),
    ({"close_produto", "unboxing"}, _VAR_PRODUTO),
]


# Formatos de CÂMERA FIXA: a câmera não se move entre as cenas (ex.: podcast, setup de
# estúdio parado). Aqui NÃO se varia o enquadramento — muda só a pose/gesto/expressão.
_CAMERA_FIXA = {"corte_podcast"}
# Formatos com AMBIENTE propositalmente PRODUZIDO (estúdio/apresentação): aí um look mais
# caprichado é OK. Todo o resto é NATIVO/AMADOR (Reels real do cotidiano), não anúncio produzido.
_PRODUZIDO = {"corte_podcast", "palestrinha"}


def _variacao_enquadramento(roteiro: dict, cena: dict) -> str:
    """Diretriz de enquadramento única desta cena, escolhida pela posição dentro do seu grupo —
    garante que cenas do mesmo tipo (ex.: várias 'avatar_fala') saiam com planos diferentes.
    EXCEÇÃO: formatos de câmera fixa (podcast) mantêm o MESMO ângulo em todas as cenas."""
    if _fmt_roteiro(roteiro) in _CAMERA_FIXA and cena.get("tipo") in PESSOA_TIPOS:
        return ("CÂMERA FIXA DE PODCAST (regra dura): use EXATAMENTE o MESMO enquadramento, ângulo, plano "
                "e distância desta pessoa em TODAS as cenas — a câmera do podcast NÃO se move. Mesma bancada/"
                "mesa no MESMO ângulo, mesma luz, mesmo fundo. Muda APENAS a POSE, o GESTO e a EXPRESSÃO de "
                "quem fala; NUNCA mude o ângulo da câmera, o plano nem a distância entre as cenas.")
    tipo = cena.get("tipo")
    # OPÇÃO 1 — ÂNCORA DE FIGURINO: a cena-âncora de uma pessoa recorrente é a que TRAVA a
    # roupa que todas as cenas dependentes vão copiar. Se ela sair num close (só rosto/busto),
    # a parte de baixo (calça/short/saia) NUNCA aparece na âncora — e cada cena que abre o
    # plano inventa uma calça diferente (era o bug do "jeans do nada"). Por isso a âncora é
    # gerada num plano ABERTO que mostra o FIGURINO COMPLETO, fixando a roupa inteira.
    if tipo in PESSOA_TIPOS and cena.get("n") in set(_mapa_ancoras(roteiro).values()):
        return ("ENQUADRAMENTO OBRIGATÓRIO desta cena (é a CENA-ÂNCORA que trava o figurino do vídeo "
                "inteiro): PLANO ABERTO / corpo inteiro (no mínimo da coxa pra cima) mostrando o "
                "FIGURINO COMPLETO da pessoa — rosto, torso E a PARTE DE BAIXO (calça/short/saia) e os "
                "calçados aparecem no quadro, pra fixar a roupa inteira que as próximas cenas vão "
                "repetir. NÃO faça close fechado só no rosto aqui; a parte de baixo do corpo TEM que "
                "estar visível.")
    for tipos, paleta in _GRUPOS:
        if tipo in tipos:
            grupo = [c for c in (roteiro.get("cenas") or []) if c.get("tipo") in tipos]
            try:
                idx = [c["n"] for c in grupo].index(cena["n"])
            except ValueError:
                idx = 0
            return ("ENQUADRAMENTO OBRIGATÓRIO desta cena (diferente das outras, nunca repita o plano "
                    "da cena anterior): " + paleta[idx % len(paleta)])
    return ""


def _ffmpeg() -> str:
    return (carregar_config().get("app", {}).get("ffmpeg") or "").strip() or "ffmpeg"


def _coletar(pasta: Path, cache: Path, limite: int) -> list[Path]:
    """Fotos utilizáveis de uma pasta, convertendo formatos exóticos via ffmpeg."""
    if not pasta.exists():
        return []
    refs: list[Path] = []
    arquivos = [p for p in sorted(pasta.iterdir()) if p.is_file() and p.name != ".gitkeep"]
    stems_ok = {p.stem.lower() for p in arquivos if p.suffix.lower() in FORMATOS_OK}
    for p in arquivos:
        ext = p.suffix.lower()
        if ext in FORMATOS_OK:
            refs.append(p)
        elif ext in FORMATOS_CONVERTER and p.stem.lower() not in stems_ok:
            cache.mkdir(parents=True, exist_ok=True)
            destino = cache / (p.stem + ".png")
            if not destino.exists():
                subprocess.run([_ffmpeg(), "-y", "-i", str(p), str(destino)],
                               capture_output=True, creationflags=_NO_WINDOW)
            if destino.exists():
                refs.append(destino)
    return refs[:limite]


def referencias_da_cena(produto: str, avatar: str | None, tipo: str,
                        tipo_prod: str = "fisico", pessoa_tipo: str = "avatar",
                        dispositivo: str = "celular",
                        reservar_ancora: bool = False) -> tuple[list[Path], str]:
    """Fotos de referência (produto + pessoa) e o bloco textual que explica cada papel.

    Físico: produto é OBRIGATÓRIO (raise se faltar). Digital (infoproduto): produto é
    OPCIONAL — se não houver foto, gera a tela a partir do briefing (noref), sem travar.
    A pessoa vem de avatares/ (avatar UGC) ou influenciadores/ (o expert)."""
    p = product_dir(produto)
    # Mesmo cache de conversão que o app irmão usa para estes produtos.
    # Prints de um infoproduto sao a identidade visual da interface. Antes eles
    # eram descartados no modo digital, forcando uma UI inventada por cena.
    digital = tipo_prod == "digital"
    is_tela = tipo in TELA_TIPOS
    limite_produto = 3 if digital else 2
    refs_produto = _coletar(p / "referencia", p / "output" / ".refs", limite_produto)
    # Produto DIGITAL só entra no quadro em cenas de TELA. Numa cena de fala/pessoa/two-shot,
    # não anexa a screenshot (senão o modelo enfia um laptop onde não cabe — o produto ali é
    # só CITADO na fala). Produto FÍSICO segue anexado em toda cena (é a identidade do objeto).
    if digital and not is_tela:
        refs_produto = []
    # Cena de TELA: adapta o print pra proporção da tela do APARELHO desta cena (celular
    # retrato / notebook 16:10 / monitor 16:9) ANTES de anexar. Sem isso o modelo agiganta/
    # deforma o aparelho pra caber o conteúdo (o "mac alto demais"). Aceita cortar — prioridade
    # é o aparelho sair realista e em tamanho real.
    if digital and is_tela and refs_produto:
        ratio, sufixo, _rot = _DISPOSITIVOS.get(dispositivo, _DISPOSITIVOS["celular"])
        cache_t = p / "output" / f".refs_{sufixo}"
        refs_produto = [_adaptar_tela(r, cache_t, ratio, sufixo) for r in refs_produto]
    if not refs_produto and not digital:
        raise RuntimeError(f"Nenhuma foto de referência em {p / 'referencia'}.")
    refs_pessoa: list[Path] = []
    if avatar and tipo in PESSOA_TIPOS:
        a = pessoa_dir(avatar, pessoa_tipo)
        # Quando esta cena TAMBÉM vai anexar a âncora (cena dependente), reservamos 1 slot pra
        # ela — assim as fotos do avatar (reforço de ROSTO) + a âncora (verdade do FIGURINO)
        # convivem sem estourar o teto duro de imagens do $imagegen.
        budget = MAX_IMGS - len(refs_produto) - (1 if reservar_ancora else 0)
        refs_pessoa = _coletar(a / "referencia", a / ".refs", max(1, budget))
    refs = refs_produto + refs_pessoa
    papel_pessoa = "INFLUENCIADOR/EXPERT" if pessoa_tipo == "influenciador" else "AVATAR"
    if digital and not is_tela:
        # Cena digital que NÃO é de tela (fala/pessoa/two-shot): o produto NÃO entra no quadro.
        if refs_pessoa:
            desc = (f"As {len(refs_pessoa)} imagens anexadas são as fotos da pessoa ({papel_pessoa}) — a "
                    "pessoa da cena é EXATAMENTE essa (mesmo rosto, cabelo). NÃO mostre a tela/o produto "
                    "nesta cena: é uma cena de pessoa falando; nada de laptop/monitor/celular no quadro. "
                    "O produto (digital) é só mencionado na fala.")
        else:
            desc = ("Não há imagens anexadas. NÃO mostre nenhuma tela, laptop, monitor ou celular nesta "
                    "cena: é uma cena de pessoa(s) na cena, e o produto (digital) é apenas mencionado na "
                    "fala, nunca exibido. Monte a cena do briefing.")
    elif refs_produto and refs_pessoa:
        desc = (
            f"São {len(refs)} imagens anexadas: as PRIMEIRAS {len(refs_produto)} são as fotos REAIS "
            f"do PRODUTO (identidade a manter igual) e as ÚLTIMAS {len(refs_pessoa)} são as fotos da "
            f"pessoa ({papel_pessoa}) — a pessoa da cena é EXATAMENTE essa (mesmo rosto, cabelo, "
            "roupa e ambiente). Passe TODAS ao $imagegen."
        )
    elif refs_pessoa:
        desc = (
            f"As {len(refs_pessoa)} imagens anexadas são as fotos da pessoa ({papel_pessoa}) — a pessoa "
            "da cena é EXATAMENTE essa (mesmo rosto, cabelo). O produto é DIGITAL e aparece numa TELA, "
            "montada a partir do briefing (interface genérica, sem marca inventada)."
        )
    elif refs_produto:
        desc = ("As imagens anexadas são a referência do PRODUTO (a identidade dele), NÃO a cena: "
                "use-as para manter o produto igual, mas monte a cena nova do briefing.")
    else:
        desc = ("Não há imagens anexadas: gere a cena inteira a partir do briefing. O produto é "
                "DIGITAL e aparece numa TELA de dispositivo (interface genérica, sem marca/logo inventado).")
    return refs, desc


def _verdade_visual(produto: str) -> str:
    f = product_dir(produto) / "contexto" / "verdade_visual.md"
    if not f.exists():
        return ""
    itens = [l.strip()[2:].strip() for l in f.read_text(encoding="utf-8", errors="replace").splitlines()
             if l.strip().startswith("- ")]
    if not itens:
        return ""
    return ("FATOS VISUAIS OBRIGATORIOS DESTE PRODUTO (valem sempre):\n" +
            "\n".join(f"- {i}" for i in itens))


def _perfil_pessoa(nome: str | None, pessoa_tipo: str = "avatar") -> str:
    if not nome:
        return ""
    perfil = pessoa_dir(nome, pessoa_tipo) / "perfil.md"
    if not perfil.exists():
        return ""
    rotulo = "DO INFLUENCIADOR/EXPERT" if pessoa_tipo == "influenciador" else "DO AVATAR"
    return f"PERFIL CANONICO {rotulo} (fatos que valem em toda cena):\n" + \
        perfil.read_text(encoding="utf-8", errors="replace")


def _fmt_roteiro(roteiro: dict) -> str:
    """Id do formato de vídeo do roteiro, normalizado (legado/desconhecido -> 'padrao')."""
    fmt = roteiro.get("formato_video") or "padrao"
    return fmt if fv.existe(fmt) else "padrao"


def _avatar_da_cena(roteiro: dict, cena: dict) -> str | None:
    """CASTING: decide qual pessoa (avatar UGC ou expert) referenciar NESTA cena — ou None
    (o Veo gera a pessoa, sem foto de referência de casa).

    - SOLO com avatar/expert resolvido -> a pessoa recorrente entra em toda cena de pessoa.
    - Casting 'gerado' (elenco_gerado) -> NUNCA anexa referência (era o bug do multi-pessoa).
    - MULTI com expert/autoridade -> referência SÓ nas cenas do papel de AUTORIDADE
      (formatos_video.papel_autoridade); o outro papel é gerado pelo Veo."""
    fmt = _fmt_roteiro(roteiro)
    if fv.two_shot(fmt):
        return None  # two-shot: a dupla é GERADA e ancorada junta (sem foto de avatar único)
    avatar = roteiro.get("avatar")
    if not avatar or roteiro.get("elenco_gerado"):
        return None
    if not fv.multi_pessoa(fmt):
        return avatar  # solo: a pessoa recorrente aparece em todas as cenas de pessoa
    elenco = str(cena.get("elenco") or "A").upper()
    return avatar if elenco == fv.papel_autoridade(fmt) else None


def _char_key(roteiro: dict, cena: dict) -> str | None:
    """Chave do PERSONAGEM GERADO desta cena (para ancorar a identidade entre cenas), ou
    None. Só vale para cenas de pessoa cujo rosto é GERADO pelo Veo (sem foto de avatar de
    casa) — nesses casos, sem uma imagem-âncora, cada cena viraria uma pessoa diferente.
    Cenas com avatar/expert real já ficam ancoradas pelas fotos, então retornam None."""
    if cena.get("tipo") not in PESSOA_TIPOS:
        return None
    fmt = _fmt_roteiro(roteiro)
    if fv.two_shot(fmt):
        return "AB"  # two-shot: ancora a DUPLA junta (mesmo par nas duas cenas)
    av = _avatar_da_cena(roteiro, cena)
    if av is not None:
        # Avatar/expert real: as fotos travam o ROSTO, mas não a ROUPA/CENÁRIO entre cenas.
        # Ancora também no 1º keyframe pra manter a MESMA roupa e o MESMO ambiente/luz.
        return f"AV::{av}"
    gerado = bool(roteiro.get("elenco_gerado"))
    multi = fv.multi_pessoa(fmt)
    if not (gerado or (multi and roteiro.get("avatar"))):
        return None  # não há pessoa gerada recorrente
    return str(cena.get("elenco") or "A").upper()


def _mapa_ancoras(roteiro: dict) -> dict[int, int]:
    """{n_cena_dependente -> n_cena_âncora}. Para cada personagem gerado, a PRIMEIRA cena
    de pessoa (menor n) é a âncora; as demais cenas do mesmo personagem apontam para ela e
    reusam o keyframe gerado como referência de identidade (mesmo rosto/cabelo/roupa)."""
    primeira: dict[str, int] = {}
    for c in roteiro.get("cenas") or []:
        k = _char_key(roteiro, c)
        if k is None:
            continue
        if k not in primeira or c["n"] < primeira[k]:
            primeira[k] = c["n"]
    dep: dict[int, int] = {}
    for c in roteiro.get("cenas") or []:
        k = _char_key(roteiro, c)
        if k is not None and primeira.get(k) != c["n"]:
            dep[c["n"]] = primeira[k]
    return dep


def montar_prompt(roteiro: dict, cena: dict, extra: str | None = None,
                  anchor: bool = False) -> str:
    digital = roteiro.get("tipo_produto") == "digital"
    # Ofertas digitais podem precisar mostrar o RESULTADO físico prometido (comida,
    # artesanato etc.) como b-roll. Nesses tipos físicos, não force notebook/tela:
    # preserve o prefixo digital apenas nas cenas que realmente exibem a entrega.
    cena_de_tela = cena.get("tipo") in TELA_TIPOS
    blocos = [PREFIXO_DIGITAL if (digital and cena_de_tela) else PREFIXO_FIDELIDADE]
    if not digital:  # verdade_visual é fidelidade de produto FÍSICO
        vv = _verdade_visual(roteiro["produto"])
        if vv:
            blocos.append(vv)
    if digital:
        blocos.append(
            "CONTRATO VISUAL DA INTERFACE DIGITAL (prioridade maxima): se houver print do produto "
            "anexado, ele e a fonte unica da verdade. Mostre exatamente a mesma interface em todas "
            "as cenas: mesmo layout, hierarquia, cores, componentes, icones, tipografia, textos e "
            "estado da tela. Nao crie uma UI alternativa, nao reorganize paineis e nao troque a tela "
            "por um dashboard inventado. Pode mudar apenas o enquadramento do dispositivo e a acao "
            "da pessoa; o conteudo da tela permanece identico e legivel. Se nao houver print, so entao "
            "use uma interface generica coerente entre as cenas."
        )
        if cena["tipo"] not in TELA_TIPOS:
            # Cena digital de FALA/pessoa (não é cena de tela): o produto NÃO aparece aqui.
            blocos.append("EXCEÇÃO DESTA CENA: aqui NÃO há tela do produto no quadro — é uma cena de "
                          "pessoa(s), não um close de tela. NÃO coloque laptop, monitor, tablet ou celular "
                          "exibindo o produto; o infoproduto é apenas MENCIONADO na fala. Mostre só a(s) "
                          "pessoa(s) e o ambiente.")
        else:
            # Cena de TELA: o aparelho é o DETECTADO nesta cena (celular/notebook/monitor). A
            # referência anexada já vem RECORTADA na proporção da tela DELE, então o aparelho
            # sai em tamanho/forma REAIS. Isto é o que mata o "celular gigante"/"mac alto demais":
            # não deixamos o modelo esticar o aparelho pra caber o conteúdo.
            _r, _s, rotulo_disp = _DISPOSITIVOS.get(_dispositivo_da_cena(cena), _DISPOSITIVOS["celular"])
            blocos.append(f"DISPOSITIVO DESTA CENA (regra dura): o produto aparece na tela de {rotulo_disp}, "
                          "de TAMANHO REAL e com a PROPORÇÃO CORRETA do aparelho — NUNCA agigantado, esticado, "
                          "achatado ou deformado pra caber o conteúdo (um notebook tem tela widescreen, um "
                          "celular tela alta e estreita). A imagem de referência da tela JÁ está na proporção "
                          "EXATA da tela DESTE aparelho: reproduza-a preenchendo a tela de BORDA A BORDA, sem "
                          "esticar, espremer, deixar barras/moldura nem reorganizar o layout. Se algo não couber, "
                          "pode ficar CORTADO nas bordas — prioridade é o APARELHO sair realista e em tamanho "
                          "real, com a tela nítida. É este aparelho e só ele; não troque por outro tipo nem "
                          "invente um dispositivo de proporção esquisita.")
    # CASTING POR PAPEL: qual pessoa (se alguma) referenciar nesta cena.
    #  - av_cena != None  -> anexa a identidade daquela pessoa (avatar UGC ou expert).
    #  - multi/gerado sem referência -> o Veo GERA a pessoa (autoridade ou 2º interlocutor).
    #  - sem pessoa -> nada de rostos (só produto/tela/mãos).
    is_pessoa = cena["tipo"] in PESSOA_TIPOS
    fmt = _fmt_roteiro(roteiro)
    multi = fv.multi_pessoa(fmt)
    gerado = bool(roteiro.get("elenco_gerado"))
    two = fv.two_shot(fmt)
    av_cena = _avatar_da_cena(roteiro, cena)
    pa = _perfil_pessoa(av_cena, roteiro.get("pessoa_tipo", "avatar")) if (av_cena and is_pessoa) else ""
    if is_pessoa and two:
        # TWO-SHOT: as DUAS pessoas juntas no mesmo quadro (ex.: entrevista de rua). Só quem
        # está no `elenco` fala/lipsync; a outra reage. A dupla é ancorada junta (char "AB").
        fala = str(cena.get("elenco") or "A").upper()
        if anchor:
            blocos.append("ÂNCORA DA DUPLA (prioridade máxima): a ÚLTIMA imagem anexada mostra AS DUAS "
                          "pessoas desta cena e o LOCAL, geradas numa cena anterior deste vídeo. Reproduza "
                          "EXATAMENTE as MESMAS duas pessoas (rosto, cabelo, FIGURINO COMPLETO — incluindo a "
                          "MESMA calça/parte de baixo e calçados —, idade, tom de cada uma) E o MESMO cenário/"
                          "local e luz da referência (mesma rua/ambiente, mesmos prédios, mesma iluminação) — é "
                          "o MESMO corte de entrevista. O figurino das duas é FIXO: NUNCA invente uma peça de "
                          "baixo diferente quando a câmera abre. Mude APENAS o ÂNGULO/plano da câmera e quem "
                          "está falando; NÃO troque de rua nem de cenário entre as cenas.")
        blocos.append(f"TWO-SHOT (regra dura): há DUAS pessoas JUNTAS no MESMO quadro, interagindo — NÃO é "
                      f"corte alternado e NÃO é uma pessoa só. As duas são CLARAMENTE DISTINTAS entre si "
                      f"(rosto, cabelo, roupa, idade, tom). Nesta cena, quem FALA é a pessoa \"{fala}\" (boca "
                      f"levemente aberta, dirigindo-se à outra); a outra ESCUTA e reage. Componha as duas "
                      f"naturalmente no plano; nunca as duas falando ao mesmo tempo, nunca uma pessoa só.")
    elif pa:
        blocos.append(pa)
        if anchor:
            # Cena ancorada: a âncora é a autoridade de FIGURINO + cenário; o perfil de texto e as
            # fotos do avatar reforçam o ROSTO e confirmam o figurino canônico (look fixo). O figurino
            # é FIXO no vídeo — a parte de baixo (calça/short/saia) nunca muda entre as cenas.
            blocos.append("CONTINUIDADE (âncora, prioridade máxima): a ÚLTIMA imagem anexada é um FRAME ANTERIOR "
                          "desta MESMA pessoa neste mesmo vídeo e é a AUTORIDADE do FIGURINO e do cenário desta "
                          "cena. Reproduza EXATAMENTE o mesmo rosto, cabelo/penteado e barba, o MESMO FIGURINO "
                          "COMPLETO (mesmo top, MESMA calça/short/saia — a PARTE DE BAIXO —, mesmos calçados e "
                          "acessórios) e o MESMO cenário/ambiente e luz da âncora. O figurino é FIXO no vídeo "
                          "inteiro: NUNCA troque a calça, o short, a saia nem qualquer peça entre as cenas, e "
                          "NUNCA invente uma peça de baixo (ex.: um jeans do nada) quando a câmera abre e mostra "
                          "o corpo — se a âncora não revelar a parte de baixo, mantenha-a coerente com o figurino "
                          "canônico do perfil de texto acima, sem inventar. O perfil e as fotos da pessoa "
                          "reforçam o ROSTO e o figurino canônico. Mude APENAS o ângulo/plano da câmera e a ação; "
                          "NÃO troque de roupa nem de cômodo entre as cenas.")
        else:
            blocos.append("IDENTIDADE DA PESSOA: use exclusivamente o rosto e os traços das fotos de referência "
                          "do avatar/influenciador selecionado. Nomes citados na narração ou no prompt não são "
                          "outras pessoas e nunca podem substituir essa identidade.")
        blocos.append("REGRA DURA DE ELENCO: há EXATAMENTE UMA pessoa na imagem, a pessoa das referências. "
                      "Não adicione amigos, colegas, pessoas desfocadas ao fundo, reflexos humanos ou uma "
                      "segunda pessoa em telas/ambientes.")
    elif is_pessoa and (gerado or (multi and roteiro.get("avatar"))):
        # Pessoa GERADA pelo Veo (sem foto de casa): ou o 2º interlocutor de um multi com
        # expert na autoridade, ou todo o elenco quando o casting é "gerado".
        elenco = str(cena.get("elenco") or "A").upper()
        if anchor:
            # Já existe um keyframe ÂNCORA deste mesmo personagem (cena anterior): a última
            # imagem anexada é ele. Aqui a regra é REPRODUZIR, não reinventar a pessoa.
            blocos.append("ÂNCORA DE IDENTIDADE (prioridade máxima): a ÚLTIMA imagem anexada é a MESMA "
                          "pessoa desta cena e o MESMO local, gerada numa cena anterior deste vídeo. Reproduza "
                          "EXATAMENTE o mesmo rosto, cabelo, barba/traços, cor de pele, idade e o MESMO FIGURINO "
                          "COMPLETO (mesmo top, MESMA calça/short/saia — a PARTE DE BAIXO —, mesmos calçados), "
                          "E o MESMO cenário/ambiente e luz da referência (mesmo cômodo/estúdio, mesmos móveis, "
                          "mesma iluminação); mude APENAS o ângulo/plano da câmera e a ação. O figurino é FIXO: "
                          "NUNCA invente uma calça/peça de baixo diferente quando a câmera abre e mostra o corpo. "
                          "NÃO troque de ambiente entre as cenas. Há EXATAMENTE UMA pessoa na imagem.")
        elif elenco != fv.papel_autoridade(fmt):
            blocos.append("SEGUNDA PESSOA (INTERLOCUTOR da conversa): esta cena mostra o OUTRO personagem, "
                          "uma pessoa CLARAMENTE DISTINTA do outro papel (outro rosto, cabelo, roupa, idade "
                          "e tom), coerente com a função dela na conversa. Há EXATAMENTE UMA pessoa na "
                          "imagem; NÃO use fotos de referência de avatar de casa aqui, e nunca coloque as "
                          "duas pessoas no mesmo quadro (o diálogo é por corte alternado). O Veo gera esta "
                          "pessoa a partir do briefing/voz.")
        else:
            blocos.append("PESSOA GERADA (autoridade/protagonista): esta cena mostra a pessoa principal do "
                          "vídeo, GERADA a partir do briefing e coerente com o cenário (nada de foto de "
                          "referência de avatar de casa). Há EXATAMENTE UMA pessoa na imagem; mantenha o "
                          "mesmo visual dela entre as cenas do mesmo papel.")
    else:
        blocos.append("REGRA DURA DE ELENCO: não há avatar selecionado. Não mostre rostos nem pessoas "
                      "identificáveis; use apenas produto/tela e mãos neutras quando a cena exigir.")
    var = _variacao_enquadramento(roteiro, cena)
    if var:
        blocos.append(var)
    blocos.append(cena["prompt_keyframe"])
    blocos.append(qualidade.reforco_prompt(cena))
    if extra:
        blocos.append(f"AJUSTE PEDIDO PELO USUARIO (prioridade máxima): {extra}")
    # REALISMO por natureza do formato: nativo/amador na maioria; produzido só onde o formato pede.
    if _fmt_roteiro(roteiro) in _PRODUZIDO:
        blocos.append("AMBIENTE PRODUZIDO: este formato tem cenário propositalmente produzido (estúdio/"
                      "apresentação) — pode ter luz mais caprichada e cenário organizado, mas ainda 100% "
                      "FOTOGRÁFICO e REAL (nunca CGI/render/3D, nunca anúncio glossy de revista, pele com "
                      "textura real).")
    else:
        blocos.append("REALISMO NATIVO (regra dura, prioridade máxima): esta cena é um vídeo REAL e AMADOR "
                      "de celular — tipo um Reels/TikTok do cotidiano, NÃO um anúncio produzido. Luz natural "
                      "do ambiente (pode ser dura/imperfeita), leve grão/ruído de sensor, cores reais SEM "
                      "color grading, PELE com textura real (poros, brilho, fios soltos, pequenas "
                      "imperfeições), enquadramento levemente torto/descentrado de quem segura o próprio "
                      "celular. PROIBIDO: iluminação de estúdio/3 pontos, pele lisa de revista, composição "
                      "perfeita, visual cinematográfico/publicitário, aparência de render/CGI/3D. Tem que "
                      "parecer que uma pessoa comum gravou no dia a dia, não uma produção.")
    # ESCALA REAL — regra inline em TODO keyframe (vale pra todo objeto/produto/dispositivo,
    # físico e digital). Antes só vivia no prefixo do diretor; aqui garante em toda geração.
    blocos.append("ESCALA REAL (regra dura, prioridade máxima): TODO objeto, produto e dispositivo "
                  "(notebook, celular, monitor, embalagem, qualquer prop) aparece em TAMANHO FÍSICO REAL e "
                  "proporção crível com a pessoa e o ambiente — apoiado na mão/mesa/colo. NUNCA gigante, "
                  "maior que a pessoa, flutuando, deformado, esticado, curvado, derretido nem colado/encostado "
                  "na lente ocupando o quadro. Um notebook tem tamanho de notebook, um celular de celular. "
                  "Se fosse ficar grande ou distorcido, AFASTE a câmera e mostre o objeto inteiro em ângulo "
                  "natural, com a mão/mesa dando escala — melhor menor e correto do que grande e distorcido.")
    blocos.append("Formato: vertical 9:16 (1024x1536), frame de vídeo caseiro fotorrealista.")
    return "\n\n".join(blocos)


def gerar_um_keyframe(roteiro: dict, cena: dict, out_dir: Path, cancel_event=None,
                      extra: str | None = None) -> str:
    cfg = carregar_config().get("keyframes", {})
    # CASTING: só anexa fotos de referência quando o papel/elenco desta cena pede uma pessoa
    # recorrente (solo, ou o papel de AUTORIDADE em multi). Nos demais (2º interlocutor,
    # elenco gerado, sem pessoa) fica None e o Veo gera a pessoa a partir do briefing.
    av_cena = _avatar_da_cena(roteiro, cena)
    disp = _dispositivo_da_cena(cena)   # celular/notebook/monitor desta cena (do prompt_keyframe)
    # ÂNCORA DE IDENTIDADE: se esta cena é de um personagem recorrente e a cena-âncora dele já
    # tem keyframe em disco, esse keyframe entra como referência da pessoa — assim rosto, cabelo,
    # FIGURINO e cenário se mantêm iguais entre as cenas. O agendador garante a âncora pronta antes.
    # OPÇÃO 2: mesmo com âncora, mantemos as fotos CRUAS do avatar anexadas — elas reforçam o
    # ROSTO. A âncora continua sendo a AUTORIDADE do figurino e do cenário (a desc abaixo e o
    # prompt deixam a hierarquia clara: figurino/cenário vêm da âncora, rosto vem das duas).
    # Reservamos 1 slot pra âncora não estourar o teto de imagens.
    anchor_path = None
    anchor_n = _mapa_ancoras(roteiro).get(cena["n"])
    if anchor_n:
        cand = out_dir / f"cena_{anchor_n:02d}.png"
        if cand.exists():
            anchor_path = cand
    refs, desc = referencias_da_cena(
        roteiro["produto"], av_cena, cena["tipo"],
        tipo_prod=roteiro.get("tipo_produto", "fisico"),
        pessoa_tipo=roteiro.get("pessoa_tipo", "avatar"),
        dispositivo=disp, reservar_ancora=bool(anchor_path))
    if anchor_path:
        refs = refs + [anchor_path]
        if fv.two_shot(_fmt_roteiro(roteiro)):
            desc = (desc + f" A ÚLTIMA das {len(refs)} imagens mostra AS DUAS pessoas E o LOCAL desta cena (as "
                    "MESMAS, geradas antes) e é a AUTORIDADE do figurino e do cenário: reproduza as duas "
                    "identidades e as roupas idênticas (mesmo top, MESMA calça/parte de baixo, mesmos calçados) "
                    "E o mesmo cenário/rua e luz; mude só o ângulo da câmera. As fotos anexadas antes servem só "
                    "pra reforçar os ROSTOS.")
        else:
            desc = (desc + f" A ÚLTIMA das {len(refs)} imagens é a REFERÊNCIA de FIGURINO, identidade E de cenário "
                    "desta cena (a MESMA pessoa e o MESMO ambiente, gerados antes) e MANDA sobre a roupa: copie "
                    "rosto, cabelo, barba, cor de pele e o FIGURINO COMPLETO idênticos (mesmo top, MESMA calça/"
                    "parte de baixo, mesmos calçados) E o mesmo cenário/luz; mude só o ângulo da câmera. As fotos "
                    "da pessoa anexadas antes servem só pra reforçar o ROSTO — nunca pra trocar a roupa.")
    prompt = montar_prompt(roteiro, cena, extra=extra, anchor=bool(anchor_path))
    out_file = out_dir / f"cena_{cena['n']:02d}.png"
    tmp = out_dir / f".cena_{cena['n']:02d}.{uuid.uuid4().hex}.tmp.png"
    backend = cfg.get("backend", "codex")
    if backend == "api":
        from backends import api_backend as be
        be.generate(prompt, refs, tmp, size=cfg.get("size", "1024x1536"),
                    timeout=int(cfg.get("timeout", 600)), anexos_desc=desc)
    else:
        from backends import codex_backend as be
        scratch = out_dir / ".codex_scratch" / uuid.uuid4().hex
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            be.generate(prompt, refs, tmp, size=cfg.get("size", "1024x1536"),
                        timeout=int(cfg.get("timeout", 600)), workdir=str(scratch),
                        cancel_event=cancel_event,
                        reasoning=(cfg.get("reasoning") or None),
                        model=(cfg.get("img_model") or None),
                        anexos_desc=desc)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    tmp.replace(out_file)
    return out_file.name


def gerar_keyframe_validado(roteiro: dict, cena: dict, out_dir: Path,
                            cancel_event=None, extra: str | None = None,
                            on_estado=None) -> tuple[str, dict, int]:
    """Gera, analisa e regenera o keyframe antes de liberar qualquer animação paga."""
    qcfg = carregar_config().get("qualidade", {})
    limite = max(1, int(qcfg.get("max_tentativas_keyframe", 3)))
    correcao = extra
    ultima = {}
    for tentativa in range(1, limite + 1):
        if on_estado:
            on_estado("gerando" if tentativa == 1 else "regenerando", tentativa,
                      ultima.get("motivos", []), tentativa - 1)
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Geração cancelada.")
        nome = gerar_um_keyframe(roteiro, cena, out_dir, cancel_event=cancel_event, extra=correcao)
        path = out_dir / nome
        # Continuidade visual: compare o candidato com até dois keyframes aprovados do
        # mesmo vídeo. O último anexo continua sendo sempre o candidato.
        # Nunca use arquivos órfãos de uma versão/avatar anterior. Só o roteiro atual
        # decide quais imagens estão aprovadas para ancorar identidade e figurino.
        refs_qa = []
        for outra in roteiro.get("cenas", []):
            kf = outra.get("keyframe") or {}
            nome_ref = kf.get("arquivo")
            if kf.get("aprovado") and nome_ref:
                ref = out_dir / nome_ref
                if ref != path and ref.exists():
                    refs_qa.append(ref)
            if len(refs_qa) >= 2:
                break
        ultima = qualidade.avaliar_keyframe(path, cena, referencias=refs_qa)
        if ultima.get("aprovado"):
            return nome, ultima, tentativa
        qualidade.arquivar_descarte(out_dir.parent, cena, "keyframe", path, ultima,
                                    montar_prompt(roteiro, cena, extra=correcao))
        path.unlink(missing_ok=True)
        if on_estado:
            on_estado("reprovado_regenerando", tentativa, ultima.get("motivos", []), tentativa)
        correcao = (ultima.get("correcao_prompt") or
                    "Corrija rigorosamente os defeitos visuais apontados na análise anterior.")
    motivos = "; ".join(str(x.get("detalhe") or x.get("codigo")) for x in ultima.get("motivos", []))
    raise RuntimeError(f"Keyframe reprovado após {limite} tentativas: {motivos}")


def _salvar_qualidade(rot_file: Path, lock: threading.Lock, n: int, etapa: str,
                      analise: dict, tentativas: int) -> None:
    with lock:
        atual = ler_json(rot_file)
        for c in atual.get("cenas", []):
            if c["n"] == n:
                if etapa == "keyframe":
                    c["keyframe"]["aprovado"] = True
                c["qualidade"] = {"estado": "aprovado", "etapa": etapa,
                                  "tentativa": tentativas, "motivos": [],
                                  "descartes": max(0, tentativas - 1), "analise": analise}
        atomic_write_json(rot_file, atual)


def gerar_keyframes(produto: str, vid: str, ns: list[int] | None = None,
                    cancel_event=None) -> None:
    """Gera os keyframes pendentes (ou só os de `ns`). Roda em thread de background."""
    d = video_dir(produto, vid)
    rot_file = d / "roteiro.json"
    roteiro = ler_json(rot_file)
    out_dir = d / "keyframes"
    out_dir.mkdir(parents=True, exist_ok=True)

    alvo = [c for c in roteiro["cenas"]
            if (ns and c["n"] in ns) or (not ns and not c["keyframe"]["arquivo"])]
    status = JobStatus(d / "status.json", "keyframes", len(alvo))
    rot_lock = threading.Lock()

    def _salvar_cena(cena, nome_arq, erro=None):
        with rot_lock:
            atual = ler_json(rot_file) or roteiro
            for c in atual["cenas"]:
                if c["n"] == cena["n"]:
                    if nome_arq:
                        c["keyframe"]["arquivo"] = nome_arq
                        c["keyframe"]["aprovado"] = True
                        c["keyframe"]["tentativas"] = int(c["keyframe"].get("tentativas") or 0) + 1
                        # keyframe novo invalida clipe antigo da cena
                        c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                                      "erro": None, "lipsync_aplicado": False}
            atomic_write_json(rot_file, atual)
            roteiro.update(atual)

    def _job(cena):
        if cancel_event is not None and cancel_event.is_set():
            return
        rotulo = f"cena_{cena['n']:02d}"
        status.comecou(rotulo)
        try:
            def _estado(estado, tentativa, motivos, descartes):
                with rot_lock:
                    atual = ler_json(rot_file) or roteiro
                    for c in atual["cenas"]:
                        if c["n"] == cena["n"]:
                            c["qualidade"] = {"estado": estado, "etapa": "keyframe",
                                              "tentativa": tentativa, "motivos": motivos,
                                              "descartes": descartes}
                    atomic_write_json(rot_file, atual)
            nome, analise, tentativas = gerar_keyframe_validado(
                roteiro, cena, out_dir, cancel_event=cancel_event, on_estado=_estado)
            _salvar_cena(cena, nome)
            _salvar_qualidade(rot_file, rot_lock, cena["n"], "keyframe", analise, tentativas)
            status.terminou(rotulo)
        except Exception as e:  # noqa: BLE001
            if cancel_event is None or not cancel_event.is_set():
                status.terminou(rotulo, erro=str(e))
                # Marca a cena como REPROVADA (não "regenerando" stale) pra a UI mostrar o
                # estado certo + os botões "Gerar de novo"/"Aceitar assim mesmo".
                with rot_lock:
                    atual = ler_json(rot_file) or roteiro
                    for c in atual["cenas"]:
                        if c["n"] == cena["n"]:
                            c["qualidade"] = {"estado": "reprovado", "etapa": "keyframe",
                                              "tentativa": 0, "motivos": [{"detalhe": str(e)}],
                                              "descartes": 0}
                    atomic_write_json(rot_file, atual)
            else:
                status.terminou(rotulo)

    # Duas ondas: 1) âncoras + cenas independentes; 2) cenas que dependem de uma âncora
    # (mesmo personagem gerado). Assim o keyframe-âncora já existe em disco quando a cena
    # dependente é gerada e pode ser reusado como referência de identidade.
    dep = _mapa_ancoras(roteiro)
    ondas = [[c for c in alvo if c["n"] not in dep], [c for c in alvo if c["n"] in dep]]
    workers = max(1, int(carregar_config().get("keyframes", {}).get("workers", 6)))
    try:
        for onda in ondas:
            if not onda:
                continue
            with ThreadPoolExecutor(max_workers=min(workers, len(onda))) as ex:
                list(ex.map(_job, onda))
    finally:
        status.fim(cancelado=bool(cancel_event is not None and cancel_event.is_set()))


def _lote_status_path(produto: str) -> Path:
    return VIDEOS / produto / "lote_status.json"


def gerar_keyframes_lote(produto: str, vids: list[str], cancel_event=None) -> None:
    """Gera os keyframes de VÁRIOS vídeos em UM lote: junta todas as cenas pendentes
    de todos os vídeos e roda em paralelo até o teto (config keyframes.workers, 6),
    fila rolante — igual aos criativos estáticos. Ex.: 5 vídeos x 8 cenas = 40 frames
    gerados de 6 em 6. Cada keyframe é salvo no roteiro.json do seu próprio vídeo.
    Progresso agregado em videos/<produto>/lote_status.json."""
    ctx: dict[str, tuple] = {}   # vid -> (rot_file, roteiro, out_dir, lock)
    tarefas: list[tuple] = []    # (vid, cena)
    for vid in vids:
        try:
            d = video_dir(produto, vid)
        except Exception:  # noqa: BLE001
            continue
        rot_file = d / "roteiro.json"
        roteiro = ler_json(rot_file)
        if not roteiro:
            continue
        out_dir = d / "keyframes"
        out_dir.mkdir(parents=True, exist_ok=True)
        ctx[vid] = (rot_file, roteiro, out_dir, threading.Lock())
        dep_vid = _mapa_ancoras(roteiro)
        for c in roteiro.get("cenas", []):
            if not (c.get("keyframe") or {}).get("arquivo"):
                # onda 0 = âncora/independente, onda 1 = depende de âncora
                tarefas.append((vid, c, 1 if c["n"] in dep_vid else 0))

    total = len(tarefas)
    status = JobStatus(_lote_status_path(produto), "keyframes_lote", total)
    if total == 0:
        status.fim()
        return

    def _job(tarefa):
        vid, cena = tarefa[0], tarefa[1]
        if cancel_event is not None and cancel_event.is_set():
            return
        rot_file, roteiro, out_dir, lock = ctx[vid]
        rotulo = f"{vid[-6:]}/cena_{cena['n']:02d}"
        status.comecou(rotulo)
        try:
            def _estado(estado, tentativa, motivos, descartes):
                with lock:
                    atual = ler_json(rot_file) or roteiro
                    for c in atual["cenas"]:
                        if c["n"] == cena["n"]:
                            c["qualidade"] = {"estado": estado, "etapa": "keyframe",
                                              "tentativa": tentativa, "motivos": motivos,
                                              "descartes": descartes}
                    atomic_write_json(rot_file, atual)
            nome, analise, tentativas = gerar_keyframe_validado(
                roteiro, cena, out_dir, cancel_event=cancel_event, on_estado=_estado)
            with lock:
                atual = ler_json(rot_file) or roteiro
                for c in atual["cenas"]:
                    if c["n"] == cena["n"] and nome:
                        c["keyframe"]["arquivo"] = nome
                        c["keyframe"]["aprovado"] = True
                        c["keyframe"]["tentativas"] = int(c["keyframe"].get("tentativas") or 0) + 1
                        c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                                      "erro": None, "lipsync_aplicado": False}
                        c["qualidade"] = {"estado": "aprovado", "etapa": "keyframe",
                                          "tentativa": tentativas, "motivos": [],
                                          "descartes": max(0, tentativas - 1),
                                          "analise": analise}
                atomic_write_json(rot_file, atual)
                roteiro.update(atual)
            status.terminou(rotulo)
        except Exception as e:  # noqa: BLE001
            if cancel_event is None or not cancel_event.is_set():
                status.terminou(rotulo, erro=str(e))
            else:
                status.terminou(rotulo)

    # Onda 0 (âncoras + independentes de TODOS os vídeos) antes da onda 1 (dependentes),
    # pra cada keyframe-âncora já estar em disco quando a cena do mesmo personagem gerar.
    ondas = [[t for t in tarefas if t[2] == 0], [t for t in tarefas if t[2] == 1]]
    workers = max(1, int(carregar_config().get("keyframes", {}).get("workers", 6)))
    try:
        for onda in ondas:
            if not onda:
                continue
            with ThreadPoolExecutor(max_workers=min(workers, len(onda))) as ex:
                list(ex.map(_job, onda))
    finally:
        status.fim(cancelado=bool(cancel_event is not None and cancel_event.is_set()))
