"""Etapa 5: montagem final GRÁTIS via ffmpeg.

1) normaliza cada cena (720x1280/30fps/H.264) e muxa a narração da cena;
2) concatena (cortes secos = jump cuts UGC);
3) queima legendas .ass estilo UGC + loudnorm + faststart.
"""
from __future__ import annotations

import re
import json
import shutil
import time
import subprocess
from pathlib import Path

from workspace import atomic_write_json, carregar_config, ler_json, video_dir
from app.pipeline import fala_veo, qualidade

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ffmpeg() -> str:
    return (carregar_config().get("app", {}).get("ffmpeg") or "").strip() or "ffmpeg"


def _ffprobe() -> str:
    f = _ffmpeg()
    return f[:-6] + "ffprobe" + f[-4:] if f.lower().endswith("ffmpeg.exe") \
        else (f[:-6] + "ffprobe" if f.lower().endswith("ffmpeg") else "ffprobe")


def _run(args: list[str], timeout: int = 600) -> None:
    r = subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr.decode(errors='replace')[-800:]}")


def _duracao(path: Path) -> float:
    r = subprocess.run(
        [_ffprobe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, creationflags=_NO_WINDOW, timeout=60)
    try:
        return float(r.stdout.decode().strip())
    except ValueError:
        return 0.0


def _silencios(clip: Path, noise: str = "-30dB", dmin: float = 0.25) -> list[tuple[float, float | None]]:
    """Intervalos de SILÊNCIO (start, end) do clipe via ffmpeg silencedetect. end=None = vai até o fim."""
    r = subprocess.run(
        [_ffmpeg(), "-i", str(clip), "-af", f"silencedetect=noise={noise}:d={dmin}", "-f", "null", "-"],
        capture_output=True, creationflags=_NO_WINDOW, timeout=120)
    err = r.stderr.decode(errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", err)]
    out: list[tuple[float, float | None]] = []
    for i, s in enumerate(starts):
        out.append((s, ends[i] if i < len(ends) else None))
    return out


def _corte_auto(clip: Path, dur: float, sugestao: dict | None = None,
                pad_ini: float = 0.06, pad_fim: float = 0.18) -> tuple[float, float]:
    """Calcula (inicio_s, fim_s) aparando o SILÊNCIO de ponta (dead air) da fala. Conservador:
    só corta silêncio colado no começo/fim; nunca deixa a cena com menos de ~1s (segurança)."""
    inicio, fim = 0.0, dur
    for s, e in _silencios(clip):
        if s <= 0.30 and e is not None:                 # silêncio de ABERTURA -> começa onde a fala entra
            inicio = max(inicio, max(0.0, e - pad_ini))
        if e is None or e >= dur - 0.08:                # silêncio até o FIM -> corta o rabo morto
            fim = min(fim, s + pad_fim)
    if sugestao and not sugestao.get("fala_inicial_embolada"):
        # O alinhamento ao roteiro remove palavras/sílabas fantasmas que não são silêncio.
        inicio = max(inicio, max(0.0, float(sugestao.get("inicio_s") or 0.0)))
        fim_sugerido = float(sugestao.get("fim_s") or 0.0)
        if fim_sugerido > 0:
            fim = min(fim, fim_sugerido)
    if fim - inicio < 1.0:                              # trim exagerado: cancela e mantém o clipe inteiro
        return 0.0, dur
    return round(inicio, 2), round(fim, 2)


def aparar_auto(produto: str, vid: str) -> None:
    """Preenche edicao.inicio_s/fim_s de cada take de FALA aparando o silêncio de ponta,
    AUTOMATICAMENTE — assim o vídeo já sai sem os silêncios/'gorduras' na maioria dos casos.
    Respeita ajuste MANUAL do usuário (edicao.manual=True): nunca sobrescreve o que ele mexeu."""
    d = video_dir(produto, vid)
    rot_file = d / "roteiro.json"
    roteiro = ler_json(rot_file)
    if not roteiro:
        return
    mudou = False
    for c in roteiro.get("cenas") or []:
        cl = c.get("clipe") or {}
        if not (cl.get("gerado") and cl.get("arquivo")):
            continue
        ed = c.get("edicao") or {}
        if ed.get("manual"):        # usuário já ajustou na timeline: respeita 100%
            continue
        if not cl.get("eh_fala"):   # b-roll mudo não tem silêncio de fala pra aparar
            continue
        clip = d / "clipes" / cl["arquivo"]
        dur = _duracao(clip)
        if dur <= 0:
            continue
        sugestao = cl.get("corte_sugerido")
        if not sugestao:
            detalhe = cl.get("transcricao_detalhada")
            if detalhe:
                sugestao = qualidade.sugerir_corte_por_fala(
                    detalhe, fala_veo.adaptar(c.get("narracao") or ""), dur)
        ini, fim = _corte_auto(clip, dur, sugestao=sugestao)
        nova = {"inicio_s": ini, "fim_s": fim, "remover": bool(ed.get("remover", False)),
                "auto": True, "sugerido_por_fala": bool(sugestao)}
        if nova != ed:
            c["edicao"] = nova
            mudou = True
    if mudou:
        atomic_write_json(rot_file, roteiro)


def _ts(seg: float) -> str:
    h = int(seg // 3600)
    m = int(seg % 3600 // 60)
    s = seg % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _quebrar(texto: str, largura: int = 26) -> str:
    """Quebra a narração em linhas curtas (\\N) pro estilo legenda de Reels."""
    palavras = texto.split()
    linhas, atual = [], ""
    for p in palavras:
        if len(atual) + len(p) + 1 > largura and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    if atual:
        linhas.append(atual)
    return "\\N".join(linhas)


def _gerar_ass(cenas_com_dur: list[tuple[dict, float]], destino: Path) -> Path:
    cab = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: UGC,Arial,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H88000000,-1,0,0,0,100,100,0,0,1,4,1,2,40,40,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    linhas = [cab]
    t = 0.0
    for cena, dur in cenas_com_dur:
        txt = (cena.get("narracao") or "").strip()
        if txt:
            linhas.append(f"Dialogue: 0,{_ts(t)},{_ts(t + dur)},UGC,,0,0,0,,{_quebrar(txt)}\n")
        t += dur
    destino.write_text("".join(linhas), encoding="utf-8-sig")
    return destino


def montar(produto: str, vid: str, legendas: bool = False, trilha: str | None = None) -> Path:
    # REGRA DURA DO LEON (nunca mudar sem ordem explícita dele): VÍDEO NUNCA leva
    # legenda queimada. O parâmetro `legendas` fica só por compatibilidade de assinatura,
    # mas é forçado a False aqui — nenhum caller consegue ligar a queima por engano.
    legendas = False
    d = video_dir(produto, vid)
    aparar_auto(produto, vid)   # auto-corta o silêncio de ponta dos takes ANTES de montar
    roteiro = ler_json(d / "roteiro.json")
    final_dir = d / "final"
    tmp_dir = d / "final" / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ff = _ffmpeg()

    cenas = [c for c in roteiro["cenas"] if c["clipe"]["gerado"] and c["clipe"]["arquivo"]
             and not (c.get("edicao") or {}).get("remover", False)]
    if not cenas:
        raise RuntimeError("Nenhum clipe gerado ainda.")

    # 1) normalizar + mux narração por cena --------------------------------
    normalizados: list[tuple[dict, Path]] = []
    for c in cenas:
        clipe = d / "clipes" / c["clipe"]["arquivo"]
        wav = d / "audio" / f"cena_{c['n']:02d}.wav"
        out = tmp_dir / f"cena_{c['n']:02d}_av.mp4"
        dur_original = _duracao(clipe)
        edicao = c.get("edicao") or {}
        inicio = max(0.0, float(edicao.get("inicio_s") or 0.0))
        fim_cfg = float(edicao.get("fim_s") or 0.0)
        fim = min(dur_original, fim_cfg) if fim_cfg > 0 else dur_original
        if fim <= inicio + 0.10:
            raise RuntimeError(f"Corte invalido na cena {c['n']}: fim precisa ser maior que inicio.")
        dur_video = fim - inicio
        vf = ("scale=720:1280:force_original_aspect_ratio=increase,"
              "crop=720:1280,fps=30,format=yuv420p")
        # Take de FALA (avatar model): o clipe JÁ vem com a voz sincronizada — usa o áudio
        # dele, sem sobrepor voiceover. Take de B-ROLL: sobrepõe a narração TTS (ou silêncio).
        clipe_tem_audio = bool(c["clipe"].get("tem_audio"))
        overlay_wav = wav.exists() and (c.get("audio") or {}).get("arquivo") and not clipe_tem_audio
        dur_audio = _duracao(wav) if overlay_wav else 0.0
        alvo = dur_video
        # Nunca esconda falta de imagem congelando o último frame. Se um áudio externo
        # não couber no take, a cena precisa ser corrigida/regenerada.
        if overlay_wav and dur_audio + 0.25 > dur_video + 0.05:
            raise RuntimeError(
                f"Cena {c['n']}: áudio ({dur_audio:.2f}s) maior que o vídeo ({dur_video:.2f}s). "
                "O take deve ser regenerado; congelamento de frame é proibido.")
        if clipe_tem_audio:
            cmd = [ff, "-y", "-ss", f"{inicio:.3f}", "-i", str(clipe),
                   "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "0:a"]
        elif overlay_wav:
            cmd = [ff, "-y", "-ss", f"{inicio:.3f}", "-i", str(clipe), "-i", str(wav),
                   "-filter_complex", f"[0:v]{vf}[v];[1:a]apad,atrim=0:{alvo:.2f}[a]",
                   "-map", "[v]", "-map", "[a]"]
        else:
            # cena sem narração ganha faixa de silêncio pro concat não desalinhar
            cmd = [ff, "-y", "-ss", f"{inicio:.3f}", "-i", str(clipe), "-f", "lavfi", "-t", f"{alvo:.2f}",
                   "-i", "anullsrc=r=48000:cl=mono",
                   "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a"]
        cmd += ["-t", f"{alvo:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                "-c:a", "aac", "-ar", "48000", "-ac", "1", str(out)]
        _run(cmd)
        normalizados.append((c, out))

    # 2) concat ------------------------------------------------------------
    lista = tmp_dir / "filelist.txt"
    lista.write_text("".join(f"file '{p.as_posix()}'\n" for _c, p in normalizados),
                     encoding="utf-8")
    bruto = tmp_dir / "bruto.mp4"
    _run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(bruto)])
    final_dir.mkdir(parents=True, exist_ok=True)

    # 3) legendas + trilha + loudnorm --------------------------------------
    final_dir.mkdir(parents=True, exist_ok=True)
    saida = final_dir / "video.mp4"
    cenas_com_dur = [(c, _duracao(p)) for c, p in normalizados]

    # 3a) trilha opcional por baixo da narração (re-mux de áudio só)
    fonte = bruto
    if trilha and Path(trilha).exists():
        com_trilha = tmp_dir / "com_trilha.mp4"
        _run([ff, "-y", "-i", str(bruto), "-stream_loop", "-1", "-i", str(trilha),
              "-filter_complex",
              "[1:a]volume=-18dB[m];[0:a][m]amix=inputs=2:duration=first[a]",
              "-map", "0:v", "-map", "[a]", "-c:v", "copy",
              "-c:a", "aac", "-ar", "48000", str(com_trilha)])
        fonte = com_trilha

    # 3b) legendas queimadas + loudnorm no passe final
    cmd = [ff, "-y", "-i", str(fonte)]
    if legendas:
        ass = _gerar_ass(cenas_com_dur, final_dir / "legendas.ass")
        # escape do caminho no Windows pro filtro ass: D\:/...
        caminho = ass.as_posix().replace(":", "\\:")
        cmd += ["-vf", f"ass='{caminho}'"]
    cmd += ["-af", "loudnorm=I=-16:TP=-1.5",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(saida)]
    _run(cmd, timeout=900)

    manual = any(bool((c.get("edicao") or {}).get("manual")) for c in cenas)
    # A primeira saída final (já normalizada/loudnorm/faststart) é a referência imutável.
    bruto_guardado = final_dir / "video-bruto.mp4"
    if not manual and not bruto_guardado.exists():
        shutil.copy2(saida, bruto_guardado)
    if manual:
        shutil.copy2(saida, final_dir / "video-ajustado.mp4")
    historico = final_dir / "historico-edicao.jsonl"
    registro = {
        "gerado_em": time.time(), "versao": "ajustada" if manual else "bruta",
        "arquivo": "video-ajustado.mp4" if manual else "video-bruto.mp4",
        "cortes": [{"n": c["n"], **(c.get("edicao") or {})} for c in cenas],
    }
    with historico.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    from workspace import atomic_write_json
    roteiro["estado"] = "montado"
    atomic_write_json(d / "roteiro.json", roteiro)
    return saida


def montar_lote(produto: str, vids: list[str], cancel_event=None) -> None:
    """Monta o vídeo final de CADA vid do lote em PARALELO (ffmpeg local, GRÁTIS) —
    cada anúncio vira 1 mp4 no seu próprio final/. Erro num vídeo não derruba os
    outros. Progresso agregado em videos/<produto>/lote_status.json (mesmo padrão de
    keyframes/clipes em lote)."""
    from concurrent.futures import ThreadPoolExecutor
    from app.pipeline._status import JobStatus
    from workspace import VIDEOS

    alvos = []
    for vid in vids:
        try:
            d = video_dir(produto, vid)
        except Exception:  # noqa: BLE001
            continue
        r = ler_json(d / "roteiro.json")
        cenas = (r or {}).get("cenas") or []
        # monta quem tem ao menos 1 clipe pronto (senão não há o que montar)
        if any((c.get("clipe") or {}).get("gerado") for c in cenas):
            alvos.append(vid)

    total = len(alvos)
    status = JobStatus(VIDEOS / produto / "lote_status.json", "montar_lote", total)
    if total == 0:
        status.fim()
        return

    def _cancelado():
        return cancel_event is not None and cancel_event.is_set()

    def _job(vid):
        if _cancelado():
            return
        rotulo = f"{vid[-6:]}/final"
        status.comecou(rotulo)
        try:
            montar(produto, vid)   # monta 1 anúncio com os clipes que existirem
            status.terminou(rotulo)
        except Exception as e:  # noqa: BLE001
            if not _cancelado():
                status.terminou(rotulo, erro=str(e))

    # ffmpeg é local/CPU (não é API paga); 4 montagens simultâneas é seguro.
    with ThreadPoolExecutor(max_workers=min(4, total)) as ex:
        list(ex.map(_job, alvos))
    status.fim()
