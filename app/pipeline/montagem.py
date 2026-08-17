"""Etapa 5: montagem final GRÁTIS via ffmpeg.

1) normaliza cada cena (720x1280/30fps/H.264) e muxa a narração da cena;
2) concatena (cortes secos = jump cuts UGC);
3) queima legendas .ass estilo UGC + loudnorm + faststart.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from workspace import carregar_config, ler_json, video_dir

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
        alvo = max(dur_video, dur_audio + 0.25) if overlay_wav else dur_video
        if alvo > dur_video + 0.05:
            vf += f",tpad=stop_mode=clone:stop_duration={alvo - dur_video:.2f}"
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

    from workspace import atomic_write_json
    roteiro["estado"] = "montado"
    atomic_write_json(d / "roteiro.json", roteiro)
    return saida
