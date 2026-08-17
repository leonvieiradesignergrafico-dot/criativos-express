"""Etapa 4: anima os keyframes aprovados (i2v) por cena, via Google Veo (omni).

Motor ÚNICO: "veo" (Vertex AI, áudio nativo). fal.ai/Wan/Higgsfield foram removidos.
Erro numa cena não derruba o lote; retry é por cena (regerar_clipe).
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from workspace import atomic_write_json, carregar_config, ler_json, pessoa_dir, video_dir
from app.pipeline._status import JobStatus
from app.pipeline import fala_veo

# Descrição de voz fixa nas cenas de fala do Veo (empurra consistência entre clipes).
# O Veo infere o gênero pela pessoa no keyframe; isto mantém timbre/estilo parecidos.
VOZ_VEO = (
    "Use the exact same speaker voice in every take of this video. Brazilian Portuguese, one adult speaker "
    "in their late 20s, warm and casual UGC delivery, clear natural timbre, medium pitch, medium vocal "
    "weight, soft natural tone, relaxed volume, and the same speaking rate. Keep the same vocal identity "
    "from beginning to end: same pitch range, resonance, accent, breathiness and energy. Do not use a "
    "deep, abnormally low-pitched, dramatic, announcer, elderly or different voice. This is one speaker, "
    "not a new voice for each scene."
)


def _voz_do_roteiro(roteiro: dict) -> str:
    """Ancora genero e identidade vocal no avatar escolhido, inclusive no voice-over."""
    perfil = ""
    nome = roteiro.get("avatar")
    if nome:
        try:
            f = pessoa_dir(nome, roteiro.get("pessoa_tipo", "avatar")) / "perfil.md"
            perfil = f.read_text(encoding="utf-8", errors="replace").casefold() if f.exists() else ""
        except ValueError:
            pass
    if any(x in perfil for x in ("homem", "masculino", "rapaz")):
        genero = "adult Brazilian male voice, clearly masculine, never a woman or feminine voice"
    elif any(x in perfil for x in ("mulher", "feminina", "moca", "moça")):
        genero = "adult Brazilian female voice, clearly feminine, never a man or masculine voice"
    else:
        genero = "adult Brazilian voice matching the visible selected avatar"
    return (
        f"{VOZ_VEO} The narrator is {genero}. The off-screen voice-over is the exact same person "
        "who speaks on camera in the other takes, with identical gender, timbre, pitch and accent."
    )


def _contexto_dos_takes(roteiro: dict, atual_n: int) -> str:
    linhas = []
    for c in roteiro.get("cenas") or []:
        papel = "ESTE TAKE" if int(c.get("n") or 0) == atual_n else "outro take"
        linhas.append(
            f"Take {c.get('n')} ({papel}, tipo {c.get('tipo')}): fala: "
            f"{(c.get('narracao') or '(sem fala)').strip()}"
        )
    return "\n".join(linhas)
# Reforço anti-distorção do produto no i2v do Veo (comida/embalagem tende a "derreter" ao animar).
FIDELIDADE_PRODUTO = ("Keep the product exactly like in the reference image — same shape, colors, "
                      "texture and details. Do NOT morph, melt, distort or restyle the product or food.")


FIDELIDADE_INTERFACE = (
    "For digital products, keep the supplied product screenshot as the single source of truth. "
    "Keep the exact same UI identity throughout the clip: identical layout, panels, colors, icons, "
    "typography, text and screen state. Do not invent, replace, rearrange or morph the interface. "
    "Use only a very subtle camera move; the screen itself remains stable and legible."
)


def _motor(nome: str | None = None):
    # Motor único: Google Veo (omni). O parâmetro é ignorado — mantido só por compatibilidade.
    from backends import veo_backend as be
    return be


def _atualizar_cena(rot_file: Path, rot_lock: threading.Lock, n: int, **campos) -> dict:
    """Read-modify-write atômico da cena `n` no roteiro.json (chaves aninhadas via dict)."""
    with rot_lock:
        atual = ler_json(rot_file)
        for c in atual["cenas"]:
            if c["n"] == n:
                for chave, valor in campos.items():
                    if isinstance(valor, dict) and isinstance(c.get(chave), dict):
                        c[chave].update(valor)
                    else:
                        c[chave] = valor
        atomic_write_json(rot_file, atual)
        return atual


def gerar_clipes(produto: str, vid: str, motor: str | None = None,
                 ns: list[int] | None = None, cancel_event=None,
                 retomar: bool = False) -> None:
    """Pipeline de clipes: TTS -> i2v -> lip-sync (só avatar_fala). Thread de background."""
    cfg = carregar_config()
    vcfg = cfg.get("video", {})
    motor = "veo"  # motor único (omni/Veo). Ignora qualquer valor de config/param.
    modelo = vcfg.get("modelo_veo", "veo_fast")
    duracao = int(vcfg.get("duracao_s", 5))
    resolution = vcfg.get("resolution", "720p")
    timeout = int(vcfg.get("timeout", 900))

    d = video_dir(produto, vid)
    rot_file = d / "roteiro.json"
    roteiro = ler_json(rot_file)
    voz_roteiro = _voz_do_roteiro(roteiro)
    rot_lock = threading.Lock()
    (d / "audio").mkdir(exist_ok=True)
    (d / "clipes").mkdir(exist_ok=True)

    cenas = [c for c in roteiro["cenas"]
             if (ns and c["n"] in ns) or (not ns and not c["clipe"]["gerado"])]
    cenas = [c for c in cenas if c["keyframe"]["arquivo"]]

    status = JobStatus(d / "status.json", "clipes", len(cenas))

    def _cancelado():
        return cancel_event is not None and cancel_event.is_set()

    def _job(cena):
        if _cancelado():
            return
        n = cena["n"]
        rotulo = f"cena_{n:02d}"
        status.comecou(rotulo)
        try:
            tem_narracao = bool(cena["narracao"].strip())
            keyframe = d / "keyframes" / cena["keyframe"]["arquivo"]
            out_mp4 = d / "clipes" / f"cena_{n:02d}.mp4"
            rid_salvo = cena["clipe"].get("fal_request_id") if retomar else None

            def _on_submit(info):
                _atualizar_cena(rot_file, rot_lock, n,
                                clipe={"fal_request_id": f"{info['endpoint']}::{info['request_id']}"})

            # No Veo (omni), TODA cena narrada usa ÁUDIO NATIVO (uma voz só no vídeo inteiro):
            # cena com pessoa -> a pessoa fala; cena de produto/tela -> voz-off do Veo. Sem TTS.
            pessoa_visivel = cena["tipo"] in ("avatar_fala", "avatar_mostra", "avatar_usa", "avatar_aponta_tela")
            veo_narrado = tem_narracao
            dur_tts = None

            if veo_narrado:
                # VEO com áudio NATIVO. Dicção adaptada, voz fixa, sem música. Uma voz no vídeo todo.
                from backends import veo_backend as be
                dialogo = fala_veo.adaptar(cena["narracao"])
                fidelidade = FIDELIDADE_INTERFACE if roteiro.get("tipo_produto") == "digital" else FIDELIDADE_PRODUTO
                instrucao_take = (cena.get("instrucao_clipe") or "").strip()
                contexto_takes = _contexto_dos_takes(roteiro, n)
                ajuste = ""
                if instrucao_take:
                    ajuste = (
                        "\nUSER REQUEST FOR THIS REGENERATION (highest priority, while preserving the exact script): "
                        f"{instrucao_take}\nVIDEO TAKE MAP (use this to resolve references such as take 2, "
                        f"previous take or other takes):\n{contexto_takes}\n"
                        "If the request mentions another take's voice, it means the same recurring speaker identity "
                        "of this video: match gender, pitch range, accent, pace, energy and vocal weight. Do not "
                        "change the spoken words."
                    )
                if pessoa_visivel:
                    prompt_fala = (
                        "The person in the reference image looks at the camera and speaks in Brazilian "
                        f"Portuguese, {voz_roteiro}. No background music, no soundtrack, only their clean "
                        "natural voice in a quiet room. They say exactly, with correct natural Brazilian "
                        f'pronunciation: "{dialogo}". Handheld selfie video, home setting, lips perfectly '
                        "synced to the speech. Authentic UGC. " + fidelidade + ajuste)
                else:
                    prompt_fala = (
                        "Gentle, minimal camera movement only (slow push-in), keep the shot stable. "
                        f"A Brazilian Portuguese voiceover, {voz_roteiro}, no background music, no soundtrack, "
                        f'says clearly off-screen, with correct Brazilian pronunciation: "{dialogo}". '
                        "No person speaking on camera in this shot. " + fidelidade + ajuste)
                # duração cobre a fala (~2,5 palavras/s), teto 8s do Veo (o _veo_dur encaixa em 4/6/8)
                palavras = len(cena["narracao"].split())
                dur_fala = max(int(cena.get("duracao_s") or duracao), round(palavras / 2.5))
                be.generate(keyframe, prompt_fala, out_mp4, duration_s=dur_fala, resolution=resolution,
                            model=modelo, gerar_audio=True, timeout=timeout,
                            cancel_event=cancel_event, request_id=rid_salvo, on_submit=_on_submit)
                clipe_audio = True
            else:
                # B-ROLL mudo (cena sem narração): Veo anima só o movimento de câmera.
                from backends import veo_backend as be
                dur_clip = int(cena.get("duracao_s") or duracao)
                movimento = cena["prompt_movimento"] or "movimento sutil de câmera handheld"
                instrucao_take = (cena.get("instrucao_clipe") or "").strip()
                if instrucao_take:
                    movimento += (
                        f" User correction for this take: {instrucao_take}. "
                        f"Take map for resolving references: {_contexto_dos_takes(roteiro, n)}."
                    )
                if roteiro.get("tipo_produto") == "digital":
                    movimento += (" Keep the supplied digital product interface completely unchanged; "
                                  "only a slow, minimal camera push-in or short pan.")
                be.generate(keyframe, movimento,
                            out_mp4, duration_s=dur_clip,
                            resolution=resolution, model=modelo, timeout=timeout,
                            cancel_event=cancel_event, request_id=rid_salvo, on_submit=_on_submit)
                clipe_audio = False

            _atualizar_cena(rot_file, rot_lock, n,
                            clipe={"arquivo": out_mp4.name, "gerado": True, "erro": None,
                                   "tem_audio": clipe_audio, "eh_fala": veo_narrado})
            status.terminou(rotulo)
        except Exception as e:  # noqa: BLE001
            _atualizar_cena(rot_file, rot_lock, n, clipe={"erro": str(e)})
            if not _cancelado():
                status.terminou(rotulo, erro=str(e))
            else:
                status.terminou(rotulo)

    # Veo paraleliza chamadas ao Vertex com teto da config.
    workers = max(1, int(vcfg.get("workers", 2)))
    try:
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(cenas)))) as ex:
            list(ex.map(_job, cenas))
        # Estado global do vídeo
        atual = ler_json(rot_file)
        if all(c["clipe"]["gerado"] for c in atual["cenas"]):
            atual["estado"] = "clipes_gerados"
            atomic_write_json(rot_file, atual)
    finally:
        status.fim(cancelado=_cancelado())
