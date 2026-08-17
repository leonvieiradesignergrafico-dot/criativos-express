"""Etapa 2: keyframes GRÁTIS (1 imagem 9:16 por cena) via backend de imagem do irmão."""
from __future__ import annotations

import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from workspace import (atomic_write_json, carregar_config, ler_json, pessoa_dir,
                       product_dir, tipo_produto, video_dir)
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


def _variacao_enquadramento(roteiro: dict, cena: dict) -> str:
    """Diretriz de enquadramento única desta cena, escolhida pela posição dentro do seu grupo —
    garante que cenas do mesmo tipo (ex.: várias 'avatar_fala') saiam com planos diferentes."""
    tipo = cena.get("tipo")
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
                        tipo_prod: str = "fisico", pessoa_tipo: str = "avatar") -> tuple[list[Path], str]:
    """Fotos de referência (produto + pessoa) e o bloco textual que explica cada papel.

    Físico: produto é OBRIGATÓRIO (raise se faltar). Digital (infoproduto): produto é
    OPCIONAL — se não houver foto, gera a tela a partir do briefing (noref), sem travar.
    A pessoa vem de avatares/ (avatar UGC) ou influenciadores/ (o expert)."""
    p = product_dir(produto)
    # Mesmo cache de conversão que o app irmão usa para estes produtos.
    # Prints de um infoproduto sao a identidade visual da interface. Antes eles
    # eram descartados no modo digital, forcando uma UI inventada por cena.
    limite_produto = 3 if tipo_prod == "digital" else 2
    refs_produto = _coletar(p / "referencia", p / "output" / ".refs", limite_produto)
    if not refs_produto and tipo_prod != "digital":
        raise RuntimeError(f"Nenhuma foto de referência em {p / 'referencia'}.")
    refs_pessoa: list[Path] = []
    if avatar and tipo in PESSOA_TIPOS:
        a = pessoa_dir(avatar, pessoa_tipo)
        refs_pessoa = _coletar(a / "referencia", a / ".refs", MAX_IMGS - len(refs_produto))
    refs = refs_produto + refs_pessoa
    papel_pessoa = "INFLUENCIADOR/EXPERT" if pessoa_tipo == "influenciador" else "AVATAR"
    if refs_produto and refs_pessoa:
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


def montar_prompt(roteiro: dict, cena: dict, extra: str | None = None) -> str:
    digital = roteiro.get("tipo_produto") == "digital"
    blocos = [PREFIXO_DIGITAL if digital else PREFIXO_FIDELIDADE]
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
    pa = (_perfil_pessoa(roteiro.get("avatar"), roteiro.get("pessoa_tipo", "avatar"))
          if cena["tipo"] in PESSOA_TIPOS else "")
    if pa:
        blocos.append(pa)
        blocos.append("IDENTIDADE DA PESSOA: use exclusivamente o rosto e os traços das fotos de referência "
                      "do avatar/influenciador selecionado. Nomes citados na narração ou no prompt não são "
                      "outras pessoas e nunca podem substituir essa identidade.")
        blocos.append("REGRA DURA DE ELENCO: há EXATAMENTE UMA pessoa na imagem, a pessoa das referências. "
                      "Não adicione amigos, colegas, pessoas desfocadas ao fundo, reflexos humanos ou uma "
                      "segunda pessoa em telas/ambientes.")
    else:
        blocos.append("REGRA DURA DE ELENCO: não há avatar selecionado. Não mostre rostos nem pessoas "
                      "identificáveis; use apenas produto/tela e mãos neutras quando a cena exigir.")
    var = _variacao_enquadramento(roteiro, cena)
    if var:
        blocos.append(var)
    blocos.append(cena["prompt_keyframe"])
    if extra:
        blocos.append(f"AJUSTE PEDIDO PELO USUARIO (prioridade máxima): {extra}")
    blocos.append("Formato: vertical 9:16 (1024x1536), frame de vídeo caseiro fotorrealista.")
    return "\n\n".join(blocos)


def gerar_um_keyframe(roteiro: dict, cena: dict, out_dir: Path, cancel_event=None,
                      extra: str | None = None) -> str:
    cfg = carregar_config().get("keyframes", {})
    refs, desc = referencias_da_cena(
        roteiro["produto"], roteiro.get("avatar"), cena["tipo"],
        tipo_prod=roteiro.get("tipo_produto", "fisico"),
        pessoa_tipo=roteiro.get("pessoa_tipo", "avatar"))
    prompt = montar_prompt(roteiro, cena, extra=extra)
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
                        c["keyframe"]["aprovado"] = False
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
            nome = gerar_um_keyframe(roteiro, cena, out_dir, cancel_event=cancel_event)
            _salvar_cena(cena, nome)
            status.terminou(rotulo)
        except Exception as e:  # noqa: BLE001
            if cancel_event is None or not cancel_event.is_set():
                status.terminou(rotulo, erro=str(e))
            else:
                status.terminou(rotulo)

    workers = max(1, int(carregar_config().get("keyframes", {}).get("workers", 4)))
    try:
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(alvo)))) as ex:
            list(ex.map(_job, alvo))
    finally:
        status.fim(cancelado=bool(cancel_event is not None and cancel_event.is_set()))
