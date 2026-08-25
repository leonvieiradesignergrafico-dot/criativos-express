"""Etapa 4: anima os keyframes aprovados (i2v) por cena, via Google Veo (omni).

Motor ÚNICO: "veo" (Vertex AI, áudio nativo). fal.ai/Wan/Higgsfield foram removidos.
Erro numa cena não derruba o lote; retry é por cena (regerar_clipe).
"""
from __future__ import annotations

import threading
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from workspace import VIDEOS, atomic_write_json, carregar_config, ler_json, pessoa_dir, video_dir
from app.pipeline._status import JobStatus
from app.pipeline import fala_veo
from app.pipeline import formatos_video as fv
from app.pipeline import qualidade

# Descrição de voz fixa nas cenas de fala do Veo (empurra consistência entre clipes).
# O Veo infere o gênero pela pessoa no keyframe; isto mantém timbre/estilo parecidos.
VOZ_VEO = (
    "Speak Brazilian Portuguese as ONE real person talking naturally on camera — spontaneous, "
    "conversational and relaxed, like chatting with a friend, NOT reading a script and NOT acting. "
    "Natural everyday rhythm and intonation, with small human imperfections, natural micro-pauses and "
    "breaths; never robotic, flat, monotone, theatrical, over-articulated or announcer-like. Keep the "
    "SAME speaker voice in every take of this video: same age (adult, late 20s to mid 30s), pitch range, "
    "timbre, accent, cadence and energy from beginning to end. One speaker, one fixed voice — never a new "
    "or different voice per scene, and never a deep dramatic announcer, elderly or robotic voice."
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
        genero = ("adult Brazilian MALE voice, clearly masculine — early-to-mid 30s, relaxed mid-low chest "
                  "pitch, even unhurried cadence, neutral Southeast-Brazilian (Sao Paulo) accent, warm "
                  "slightly grainy timbre, calm confident energy; never a deep announcer, never high or "
                  "nasal, never a woman or feminine voice")
    elif any(x in perfil for x in ("mulher", "feminina", "moca", "moça")):
        genero = ("adult Brazilian FEMALE voice, clearly feminine — late 20s, bright-but-warm mid pitch, "
                  "light friendly cadence, neutral Southeast-Brazilian (Sao Paulo) accent, clear smooth "
                  "timbre with a soft natural edge, relaxed conversational energy; never childlike, never a "
                  "breathy whisper, never a man or masculine voice")
    else:
        genero = ("adult Brazilian voice matching the visible selected avatar — neutral Southeast-Brazilian "
                  "(Sao Paulo) accent, warm natural UGC timbre, even conversational cadence")
    return (
        f"{VOZ_VEO} The narrator is {genero}. Treat this as ONE fixed voice signature: reuse the EXACT same "
        "age, pitch, timbre, cadence, accent and energy in every single take. The off-screen voice-over is "
        "the exact same person who speaks on camera in the other takes."
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


def _gerar_clipe_cena(d: Path, rot_file: Path, rot_lock: threading.Lock, roteiro: dict,
                      cena: dict, voz_roteiro: str, duracao: int, resolution: str,
                      modelo: str, timeout: int, retomar: bool, cancel_event=None) -> None:
    """Gera o clipe (Veo) de UMA cena e grava o resultado no roteiro.json.

    Compartilhado entre a geração de um vídeo (`gerar_clipes`) e o lote
    (`gerar_clipes_lote`). Em erro, registra a mensagem na cena e re-levanta —
    quem chama cuida do status/JobStatus. É thread-safe (write via `rot_lock`)."""
    n = cena["n"]
    try:
        contrato_visual = qualidade.reforco_prompt(cena)
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
        two = fv.two_shot(roteiro.get("formato_video") or "padrao")

        # Diálogo/entrevista: cena do 2º interlocutor (elenco B) usa uma voz
        # DISTINTA da principal; cenas normais mantêm a voz única do roteiro.
        if str(cena.get("elenco") or "A").upper() == "B":
            voz_cena = ("a DIFFERENT second speaker (the interlocutor), adult Brazilian Portuguese, "
                        "clearly distinct from the main speaker with a noticeably different pitch, "
                        "timbre or gender, kept consistent across this interlocutor's takes")
        else:
            voz_cena = voz_roteiro

        if veo_narrado:
            # VEO com áudio NATIVO. Dicção adaptada, voz fixa, sem música. Uma voz no vídeo todo.
            from backends import veo_backend as be
            dialogo = fala_veo.adaptar(cena["narracao"])
            fidelidade = FIDELIDADE_INTERFACE if roteiro.get("tipo_produto") == "digital" else FIDELIDADE_PRODUTO
            # Movimento por natureza do formato: nativo/amador na maioria; câmera de estúdio no produzido.
            produzido = (roteiro.get("formato_video") or "padrao") in ("corte_podcast", "palestrinha")
            movimento_nat = (
                " Steady produced studio camera (near-static, tripod feel): only calm natural head/hand "
                "movement and a tiny handheld sway."
                if produzido else
                " Natural amateur handheld PHONE motion: subtle organic sway and micro-shakes like a real "
                "person holding the phone, natural breathing and small spontaneous gestures. NOT a smooth "
                "cinematic gimbal, NOT a locked static shot, NOT a produced ad — it looks like a real "
                "everyday phone video.")
            instrucao_take = (cena.get("instrucao_clipe") or "").strip()
            ajuste = ""
            movimento_planejado = (cena.get("prompt_movimento") or "").strip()
            if movimento_planejado:
                ajuste += f"\nPLANNED MOVEMENT (must be followed literally): {movimento_planejado}\n"
            if "baba baby" in cena["narracao"].lower():
                ajuste += ("\nBRAND PRONUNCIATION OVERRIDE (hard rule): the brand is pronounced "
                           "BAH-bah BAY-bee - the English word 'baby', BAY rhyming with 'day'. The "
                           "dialogue spells it phonetically as 'Bába Beibi': read those two words "
                           "exactly as written, as ONE brand name, clearly articulated. NEVER say the "
                           "Portuguese word 'bebê' (be-BEH), never 'babá', never 'babi', and never "
                           "blur the two words into one.\n")
            contexto_takes = _contexto_dos_takes(roteiro, n)
            if instrucao_take:
                ajuste = (
                    "\nUSER REQUEST FOR THIS REGENERATION (highest priority, while preserving the exact script): "
                    f"{instrucao_take}\nVIDEO TAKE MAP (use this to resolve references such as take 2, "
                    f"previous take or other takes):\n{contexto_takes}\n"
                    "If the request mentions another take's voice, it means the same recurring speaker identity "
                    "of this video: match gender, pitch range, accent, pace, energy and vocal weight. Do not "
                    "change the spoken words."
                )
            if two and pessoa_visivel:
                # TWO-SHOT (entrevista de rua): há DUAS pessoas no quadro, mas só UMA fala nesta cena.
                # A outra fica em silêncio (boca fechada, reagindo). A voz casa com quem aparece falando
                # (nunca voz de mulher num homem, nem vice-versa) — resolve o "voz trocada / os dois falam".
                fala = str(cena.get("elenco") or "A").upper()
                quem = ("the person handling the microphone (the reporter, asking)" if fala == "B"
                        else "the person the microphone is pointed at (the interviewee, answering)")
                prompt_fala = (
                    "This is a street interview with TWO different people together in the frame. In THIS "
                    f"take, ONLY ONE of them speaks: {quem}. That single person speaks Brazilian Portuguese "
                    "looking at the other, lips perfectly synced to the words. The OTHER person stays "
                    "COMPLETELY SILENT — mouth closed, only listening and reacting with small natural nods; "
                    "never move the listener's lips, never make two people talk at once. The speaking voice "
                    "MUST match that visible speaker's apparent gender and age (a man sounds male, a woman "
                    "sounds female) and stay consistent across that same person's takes. Only ONE voice in "
                    "this take. Speak naturally and spontaneously, like a real person being interviewed on "
                    f'the street, NOT acting. They say exactly, with natural Brazilian pronunciation: "{dialogo}". '
                    "Handheld phone video, the SAME street setting as the reference image, no background "
                    "music. Authentic. " + fidelidade + movimento_nat + contrato_visual + ajuste)
            elif pessoa_visivel:
                prompt_fala = (
                    "The person in the reference image looks at the camera and speaks in Brazilian "
                    f"Portuguese, {voz_cena}. No background music, no soundtrack, only their clean "
                    "natural voice. They say exactly, with correct natural Brazilian pronunciation, "
                    f'spoken spontaneously like a real person (not acting): "{dialogo}". Handheld phone '
                    "video in the SAME setting as the reference image, lips perfectly synced to the "
                    "speech. Authentic UGC. " + fidelidade + movimento_nat + contrato_visual + ajuste)
            else:
                prompt_fala = (
                    "Gentle, minimal camera movement only (slow push-in), keep the shot stable. "
                    f"A Brazilian Portuguese voiceover, {voz_cena}, no background music, no soundtrack, "
                    f'says clearly off-screen, with correct Brazilian pronunciation: "{dialogo}". '
                    "No person speaking on camera in this shot. " + fidelidade + movimento_nat + contrato_visual + ajuste)
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
            movimento = (cena["prompt_movimento"] or "movimento sutil de câmera handheld") + contrato_visual
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
    except Exception as e:  # noqa: BLE001
        _atualizar_cena(rot_file, rot_lock, n, clipe={"erro": str(e)})
        raise


def _gerar_clipe_validado(d: Path, rot_file: Path, rot_lock: threading.Lock, roteiro: dict,
                          cena: dict, voz_roteiro: str, duracao: int, resolution: str,
                          modelo: str, timeout: int, retomar: bool, cancel_event=None) -> None:
    """Só marca o take como utilizável depois da inspeção visual automática."""
    qcfg = carregar_config().get("qualidade", {})
    limite = 1 if retomar else max(1, int(qcfg.get("max_tentativas_clipe", 3)))
    n = cena["n"]
    ultima = {}
    transcricao_anterior = None
    original = (cena.get("instrucao_clipe") or "").strip()
    for tentativa in range(1, limite + 1):
        _atualizar_cena(rot_file, rot_lock, n, qualidade={
            "estado": "gerando" if tentativa == 1 else "regenerando",
            "etapa": "clipe", "tentativa": tentativa,
            "motivos": ultima.get("motivos", []), "descartes": tentativa - 1})
        _gerar_clipe_cena(d, rot_file, rot_lock, roteiro, cena, voz_roteiro,
                          duracao, resolution, modelo, timeout, retomar, cancel_event)
        out = d / "clipes" / f"cena_{n:02d}.mp4"
        with tempfile.TemporaryDirectory(prefix=f"ce_qa_{n:02d}_") as td:
            ultima = qualidade.avaliar_clipe(out, cena, Path(td),
                                              referencia_keyframe=d / "keyframes" / cena["keyframe"]["arquivo"])
        assinatura = qualidade.assinatura_audio(out) if cena.get("narracao", "").strip() else None
        atual_rot = ler_json(rot_file) or roteiro
        referencia_voz = None
        for outra in atual_rot.get("cenas", []):
            if outra.get("n") == n or str(outra.get("elenco") or "A") != str(cena.get("elenco") or "A"):
                continue
            oc = outra.get("clipe") or {}
            if oc.get("gerado") and oc.get("arquivo") and (outra.get("narracao") or "").strip():
                referencia_voz = oc.get("assinatura_voz") or qualidade.assinatura_audio(
                    d / "clipes" / oc["arquivo"])
                if referencia_voz:
                    break
        erro_voz = qualidade.comparar_voz(assinatura, referencia_voz)
        if erro_voz:
            ultima["aprovado"] = False
            ultima.setdefault("motivos", []).append(erro_voz)
            ultima["correcao_prompt"] = ((ultima.get("correcao_prompt") or "") +
                " Use exatamente a mesma voz dos outros takes: mesmo pitch, timbre, sotaque, cadência e energia.").strip()
        if cena.get("narracao", "").strip():
            detalhe_fala = qualidade.transcrever_audio_detalhado(out)
            transcricao = detalhe_fala.get("text") if detalhe_fala else None
            erro_fala = qualidade.comparar_fala(transcricao, fala_veo.adaptar(cena["narracao"]))
            ultima["transcricao"] = transcricao
            ultima["transcricao_detalhada"] = detalhe_fala
            sugestao = qualidade.sugerir_corte_por_fala(
                detalhe_fala, fala_veo.adaptar(cena["narracao"]), qualidade._duracao_midia(out))
            ultima["corte_sugerido"] = sugestao
            if erro_fala:
                ultima["aprovado"] = False
                ultima.setdefault("motivos", []).append(erro_fala)
                ultima["correcao_prompt"] = ((ultima.get("correcao_prompt") or "") +
                    " Articule a fala inteira desde a primeira palavra, sem engolir, sobrepor ou acelerar o início.").strip()
            if sugestao and sugestao.get("fala_inicial_embolada"):
                ultima["aprovado"] = False
                ultima.setdefault("motivos", []).append({
                    "codigo": "primeira_palavra_embolada",
                    "detalhe": "a primeira palavra prevista tem baixa confiança acústica; regenere em vez de cortá-la"})
                ultima["correcao_prompt"] = ((ultima.get("correcao_prompt") or "") +
                    " Pronuncie a primeira palavra com articulação limpa e uma entrada natural, sem sílaba fantasma.").strip()
        if ultima.get("aprovado"):
            _atualizar_cena(rot_file, rot_lock, n, qualidade={
                "estado": "aprovado", "etapa": "clipe", "tentativa": tentativa,
                "motivos": [], "descartes": tentativa - 1, "analise": ultima},
                clipe={"gerado": True, "erro": None, "assinatura_voz": assinatura,
                       "transcricao_detalhada": ultima.get("transcricao_detalhada"),
                       "corte_sugerido": ultima.get("corte_sugerido")})
            return
        prompt_usado = original + "\n" + (cena.get("instrucao_clipe") or "")
        qualidade.arquivar_descarte(d, cena, "clipe", out, ultima, prompt_usado)
        out.unlink(missing_ok=True)
        # Se a fala saiu IGUAL a da tentativa anterior, o Veo esta determinstico nesta
        # cena: insistir so queima credito e devolve o mesmo audio. Para aqui.
        atual_transcricao = (ultima.get("transcricao") or "").strip()
        if atual_transcricao and transcricao_anterior and qualidade.fala_equivalente(
                atual_transcricao, transcricao_anterior):
            ultima.setdefault("motivos", []).append({
                "codigo": "regeneracao_sem_efeito",
                "detalhe": "a fala saiu identica a da tentativa anterior; parei para nao gastar clipe a toa"})
            break
        transcricao_anterior = atual_transcricao or transcricao_anterior
        correcao = ultima.get("correcao_prompt") or "Corrija os defeitos visuais detectados."
        cena["instrucao_clipe"] = (original + "\n" + correcao).strip()
        _atualizar_cena(rot_file, rot_lock, n,
                        qualidade={"estado": "reprovado_regenerando", "etapa": "clipe",
                                    "tentativa": tentativa, "motivos": ultima.get("motivos", []),
                                    "descartes": tentativa},
                        clipe={"arquivo": None, "gerado": False, "fal_request_id": None,
                               "erro": None})
    motivos = "; ".join(str(x.get("detalhe") or x.get("codigo")) for x in ultima.get("motivos", []))
    _atualizar_cena(rot_file, rot_lock, n,
                    qualidade={"estado": "reprovado", "etapa": "clipe", "tentativa": limite,
                                "motivos": ultima.get("motivos", []), "descartes": limite},
                    clipe={"arquivo": None, "gerado": False,
                           "erro": f"Reprovado pelo controle de qualidade: {motivos}"})
    raise RuntimeError(f"Clipe reprovado após {limite} tentativas: {motivos}")


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

    todos_kf = [d / "keyframes" / c["keyframe"]["arquivo"] for c in roteiro["cenas"]
                if (c.get("keyframe") or {}).get("arquivo")]
    with tempfile.TemporaryDirectory(prefix="ce_continuidade_") as td:
        continuidade = qualidade.avaliar_continuidade_video(todos_kf, Path(td), roteiro)
    if not continuidade.get("aprovado"):
        motivos = "; ".join(str((x.get("detalhe") or x.get("codigo")) if isinstance(x, dict) else x)
                            for x in continuidade.get("motivos", []))
        raise RuntimeError("Continuidade global reprovada antes dos clipes: " + motivos)

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
            _gerar_clipe_validado(d, rot_file, rot_lock, roteiro, cena, voz_roteiro,
                                  duracao, resolution, modelo, timeout, retomar, cancel_event)
            status.terminou(rotulo)
        except Exception as e:  # noqa: BLE001
            if not _cancelado():
                status.terminou(rotulo, erro=str(e))
            else:
                status.terminou(rotulo)

    # Veo paraleliza chamadas ao Vertex: 6 clipes simultâneos (igual ao lote). O retry/backoff
    # do veo_backend absorve o throttle (code 8 / high load) quando as 6 disparam juntas.
    workers = max(1, int(vcfg.get("workers", 6)))
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


def gerar_clipes_lote(produto: str, vids: list[str], cancel_event=None) -> None:
    """Gera os clipes (Veo, PAGO) de VÁRIOS vídeos em UM lote: junta as cenas
    pendentes (keyframe pronto, clipe ainda não gerado) de todos os vídeos e roda
    em paralelo até o teto (config video.workers_lote, 6), fila rolante — igual aos
    keyframes em lote. Cada clipe é salvo no roteiro.json do seu próprio vídeo.
    Progresso agregado em videos/<produto>/lote_status.json."""
    cfg = carregar_config()
    vcfg = cfg.get("video", {})
    modelo = vcfg.get("modelo_veo", "veo_fast")
    duracao = int(vcfg.get("duracao_s", 5))
    resolution = vcfg.get("resolution", "720p")
    timeout = int(vcfg.get("timeout", 900))

    ctx: dict[str, tuple] = {}   # vid -> (d, rot_file, roteiro, voz_roteiro, lock)
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
        todos_kf = [d / "keyframes" / c["keyframe"]["arquivo"] for c in roteiro["cenas"]
                    if (c.get("keyframe") or {}).get("arquivo")]
        with tempfile.TemporaryDirectory(prefix="ce_continuidade_") as td:
            continuidade = qualidade.avaliar_continuidade_video(todos_kf, Path(td), roteiro)
        if not continuidade.get("aprovado"):
            detalhes = "; ".join(str((x.get("detalhe") or x.get("codigo")) if isinstance(x, dict) else x)
                                 for x in continuidade.get("motivos", []))
            raise RuntimeError(f"{vid}: continuidade global reprovada antes dos clipes: {detalhes}")
        (d / "audio").mkdir(exist_ok=True)
        (d / "clipes").mkdir(exist_ok=True)
        voz_roteiro = _voz_do_roteiro(roteiro)
        ctx[vid] = (d, rot_file, roteiro, voz_roteiro, threading.Lock())
        for c in roteiro.get("cenas", []):
            if (not c["clipe"]["gerado"] and (c.get("keyframe") or {}).get("arquivo")
                    and (c.get("keyframe") or {}).get("aprovado")):
                tarefas.append((vid, c))

    total = len(tarefas)
    status = JobStatus(VIDEOS / produto / "lote_status.json", "clipes_lote", total)
    if total == 0:
        status.fim()
        return

    def _cancelado():
        return cancel_event is not None and cancel_event.is_set()

    def _job(tarefa):
        vid, cena = tarefa
        if _cancelado():
            return
        d, rot_file, roteiro, voz_roteiro, lock = ctx[vid]
        rotulo = f"{vid[-6:]}/cena_{cena['n']:02d}"
        status.comecou(rotulo)
        try:
            _gerar_clipe_validado(d, rot_file, lock, roteiro, cena, voz_roteiro,
                                  duracao, resolution, modelo, timeout, False, cancel_event)
            status.terminou(rotulo)
        except Exception as e:  # noqa: BLE001
            if not _cancelado():
                status.terminou(rotulo, erro=str(e))
            else:
                status.terminou(rotulo)

    # Mesma paralelização dos keyframes: 6 clipes simultâneos (fila rolante).
    workers = max(1, int(vcfg.get("workers_lote", 6)))
    try:
        with ThreadPoolExecutor(max_workers=min(workers, total)) as ex:
            list(ex.map(_job, tarefas))
        # Marca cada vídeo cujas cenas ficaram todas prontas.
        for vid, (d, rot_file, _roteiro, _voz, lock) in ctx.items():
            with lock:
                atual = ler_json(rot_file)
                if atual and all(c["clipe"]["gerado"] for c in atual["cenas"]):
                    atual["estado"] = "clipes_gerados"
                    atomic_write_json(rot_file, atual)
    finally:
        status.fim(cancelado=_cancelado())
