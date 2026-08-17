"""TTS grátis via edge-tts (vozes neurais da Microsoft, PT-BR, zero GPU).

Gera mp3 e converte pra wav 48k mono via ffmpeg (a montagem trabalha em wav).
"""
from __future__ import annotations

import asyncio
import subprocess
import wave
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VOZES_PT_BR = [
    "pt-BR-FranciscaNeural",
    "pt-BR-AntonioNeural",
    "pt-BR-ThalitaMultilingualNeural",
]


def _ffmpeg() -> str:
    from workspace import carregar_config
    return (carregar_config().get("app", {}).get("ffmpeg") or "").strip() or "ffmpeg"


def sintetizar(texto: str, output_wav, voz: dict, timeout: int = 120,
               cancel_event=None) -> float:
    """Sintetiza `texto` com a voz do avatar e salva wav. Retorna a duração em s."""
    import edge_tts

    output_wav = Path(output_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    nome_voz = (voz or {}).get("edge_voice") or "pt-BR-FranciscaNeural"
    rate = (voz or {}).get("rate") or "+0%"
    mp3 = output_wav.with_suffix(".mp3")

    async def _run():
        com = edge_tts.Communicate(texto, nome_voz, rate=rate)
        await com.save(str(mp3))

    asyncio.run(asyncio.wait_for(_run(), timeout=timeout))

    r = subprocess.run(
        [_ffmpeg(), "-y", "-i", str(mp3), "-ar", "48000", "-ac", "1", str(output_wav)],
        capture_output=True, creationflags=_NO_WINDOW, timeout=timeout,
    )
    mp3.unlink(missing_ok=True)
    if r.returncode != 0 or not output_wav.exists():
        raise RuntimeError(f"ffmpeg falhou convertendo TTS: {r.stderr.decode(errors='replace')[-400:]}")
    with wave.open(str(output_wav), "rb") as w:
        return w.getnframes() / float(w.getframerate())
