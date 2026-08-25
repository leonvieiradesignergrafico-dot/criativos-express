"""Inserts (B-roll / motion graphics) OPCIONAIS por cena.

Um insert substitui só o VÍDEO de uma cena na montagem final (o ÁUDIO/voz original da
cena continua intacto por baixo — ver `montagem.py`). É gerado em 2 passos, no mesmo
espírito dos keyframes de avatar:
  1) imagem estática (ilustração/motion graphic), aprovada manualmente antes de animar;
  2) animação via Veo i2v, SEM fala/áudio nativo (`gerar_audio=False`) — só movimento.

Não reaproveita `keyframes.gerar_um_keyframe` porque aquele fluxo carrega bagagem
específica de avatar (âncora de identidade, fotos de referência, fidelidade de produto)
que não se aplica aqui: um insert não tem pessoa nem produto físico, é puro gráfico.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from workspace import atomic_write_json, carregar_config, ler_json, video_dir

ROOT = Path(__file__).resolve().parent.parent.parent
PREFIXO_INSERT = (ROOT / "app" / "prompts" / "diretor_inserts.md").read_text(encoding="utf-8")


def montar_prompt_insert(cena: dict) -> str:
    """Prompt de geração da imagem do insert: prefixo de fidelidade + conceito da cena."""
    blocos = [PREFIXO_INSERT]
    conceito = (cena.get("insert") or {}).get("conceito") or ""
    prompt_imagem = (cena.get("insert") or {}).get("prompt_imagem") or ""
    if conceito:
        blocos.append(f"CONCEITO DESTE INSERT (o que ele precisa tangibilizar): {conceito}")
    if prompt_imagem:
        blocos.append(f"DIREÇÃO DE ARTE DESTA CENA: {prompt_imagem}")
    if cena.get("narracao"):
        blocos.append(f"Fala da cena no momento do corte (contexto, não copie o texto na arte): "
                      f"\"{cena['narracao']}\"")
    return "\n\n".join(blocos)


def gerar_imagem_insert(produto: str, vid: str, n: int) -> str:
    """Gera a imagem estática do insert da cena `n` e devolve o nome do arquivo salvo."""
    d = video_dir(produto, vid)
    roteiro = ler_json(d / "roteiro.json")
    cena = next((c for c in roteiro["cenas"] if c["n"] == n), None)
    if cena is None:
        raise ValueError(f"Cena {n} não encontrada.")
    out_dir = d / "keyframes"
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = montar_prompt_insert(cena)
    out_file = out_dir / f"insert_cena_{n:02d}.png"
    tmp = out_dir / f".insert_cena_{n:02d}.{uuid.uuid4().hex}.tmp.png"
    cfg = carregar_config().get("keyframes", {})
    backend = cfg.get("backend", "codex")
    if backend == "api":
        from backends import api_backend as be
        be.generate(prompt, [], tmp, size=cfg.get("size", "1024x1536"),
                    timeout=int(cfg.get("timeout", 600)))
    else:
        from backends import codex_backend as be
        scratch = out_dir / ".codex_scratch" / uuid.uuid4().hex
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            be.generate(prompt, [], tmp, size=cfg.get("size", "1024x1536"),
                        timeout=int(cfg.get("timeout", 600)), workdir=str(scratch),
                        reasoning=(cfg.get("reasoning") or None),
                        model=(cfg.get("img_model") or None))
        finally:
            import shutil
            shutil.rmtree(scratch, ignore_errors=True)
    tmp.replace(out_file)

    def _atualizar(rot):
        for c in rot["cenas"]:
            if c["n"] == n:
                c.setdefault("insert", {})
                c["insert"]["imagem"] = {"arquivo": out_file.name, "aprovado": False, "tentativas":
                                          int((c["insert"].get("imagem") or {}).get("tentativas", 0)) + 1}
        return rot

    _atualizar_roteiro(d, _atualizar)
    return out_file.name


def aprovar_imagem_insert(produto: str, vid: str, n: int, aprovado: bool = True) -> None:
    d = video_dir(produto, vid)

    def _atualizar(rot):
        for c in rot["cenas"]:
            if c["n"] == n:
                c.setdefault("insert", {}).setdefault("imagem", {})["aprovado"] = bool(aprovado)
        return rot

    _atualizar_roteiro(d, _atualizar)


def gerar_clipe_insert(produto: str, vid: str, n: int, duration_s: int = 5,
                       resolution: str = "720p", model: str = "veo_lite",
                       cancel_event=None) -> str:
    """Anima a imagem do insert (já aprovada) via Veo i2v, SEM fala/áudio nativo — só
    movimento. Devolve o nome do arquivo mp4 salvo em clipes/insert_cena_NN.mp4."""
    d = video_dir(produto, vid)
    roteiro = ler_json(d / "roteiro.json")
    cena = next((c for c in roteiro["cenas"] if c["n"] == n), None)
    if cena is None:
        raise ValueError(f"Cena {n} não encontrada.")
    insert = cena.get("insert") or {}
    imagem = (insert.get("imagem") or {}).get("arquivo")
    if not imagem or not (insert.get("imagem") or {}).get("aprovado"):
        raise ValueError("Aprove a imagem do insert antes de animar.")
    keyframe = d / "keyframes" / imagem
    if not keyframe.exists():
        raise ValueError("Imagem do insert não encontrada em disco.")

    clipes_dir = d / "clipes"
    clipes_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = clipes_dir / f"insert_cena_{n:02d}.mp4"
    prompt_movimento = insert.get("prompt_movimento") or (
        "Movimento sutil e contínuo, coerente com um gráfico de motion design profissional: "
        "reveal progressivo do desenho, leve parallax ou pulso de brilho. Sem pessoa, sem "
        "câmera tremida, sem distorcer a arte.")

    from backends import veo_backend as be
    be.generate(keyframe, prompt_movimento, out_mp4, duration_s=duration_s,
                resolution=resolution, model=model, cancel_event=cancel_event,
                gerar_audio=False)

    def _atualizar(rot):
        for c in rot["cenas"]:
            if c["n"] == n:
                c.setdefault("insert", {})["clipe"] = {"arquivo": out_mp4.name, "gerado": True, "erro": None}
        return rot

    _atualizar_roteiro(d, _atualizar)
    return out_mp4.name


def definir_ativo(produto: str, vid: str, n: int, ativo: bool) -> None:
    """Liga/desliga o insert desta cena (a montagem só usa o insert quando ativo=True E
    o clipe já foi gerado)."""
    d = video_dir(produto, vid)

    def _atualizar(rot):
        for c in rot["cenas"]:
            if c["n"] == n:
                c.setdefault("insert", {})["ativo"] = bool(ativo)
        return rot

    _atualizar_roteiro(d, _atualizar)


def definir_direcao(produto: str, vid: str, n: int, *, conceito: str = "",
                    prompt_imagem: str = "", prompt_movimento: str = "") -> None:
    """Grava a direção de criação do insert (conceito + prompts) sem gerar nada ainda."""
    d = video_dir(produto, vid)

    def _atualizar(rot):
        for c in rot["cenas"]:
            if c["n"] == n:
                ins = c.setdefault("insert", {})
                if conceito:
                    ins["conceito"] = conceito
                if prompt_imagem:
                    ins["prompt_imagem"] = prompt_imagem
                if prompt_movimento:
                    ins["prompt_movimento"] = prompt_movimento
        return rot

    _atualizar_roteiro(d, _atualizar)


def _atualizar_roteiro(d: Path, fn) -> None:
    """Read-modify-write simples do roteiro.json (mesmo padrão usado no resto do pipeline)."""
    rot_file = d / "roteiro.json"
    rot = ler_json(rot_file)
    rot = fn(rot)
    atomic_write_json(rot_file, rot)
