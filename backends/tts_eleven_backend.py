"""TTS via ElevenLabs (opção PAGA, a mais natural em PT-BR) — REST puro.

Requer ELEVEN_API_KEY no .env. Gera mp3 e converte pra wav 48k mono via ffmpeg.
voz.json do avatar: {"engine":"eleven","voice_id":"...","model_id":"eleven_multilingual_v2",
                     "stability":0.4,"similarity":0.75}
"""
from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path

import requests

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Voz premade padrão (multilíngue, funciona em PT-BR). O usuário pode trocar o voice_id
# por qualquer voz da biblioteca dele em elevenlabs.io/app/voice-library.
VOICE_PADRAO = "EXAVITQu4vr4xnSDxMaL"   # "Sarah" (premade)
MODELO_PADRAO = "eleven_multilingual_v2"


def _ffmpeg() -> str:
    from workspace import carregar_config
    return (carregar_config().get("app", {}).get("ffmpeg") or "").strip() or "ffmpeg"


def _key() -> str:
    k = (os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    if not k:
        raise RuntimeError("ELEVEN_API_KEY não configurada no .env (elevenlabs.io > perfil > API key).")
    return k


def sintetizar(texto: str, output_wav, voz: dict, timeout: int = 120,
               cancel_event=None) -> float:
    output_wav = Path(output_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    voz = voz or {}
    voice_id = voz.get("voice_id") or VOICE_PADRAO
    model_id = voz.get("model_id") or MODELO_PADRAO
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": _key(), "Content-Type": "application/json", "Accept": "audio/mpeg"},
        params={"output_format": "mp3_44100_128"},
        json={"text": texto, "model_id": model_id,
              "voice_settings": {"stability": float(voz.get("stability", 0.4)),
                                 "similarity_boost": float(voz.get("similarity", 0.75)),
                                 "style": float(voz.get("style", 0.0)),
                                 "use_speaker_boost": True}},
        timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs recusou ({r.status_code}): {r.text[:400]}")
    mp3 = output_wav.with_suffix(".mp3")
    mp3.write_bytes(r.content)
    conv = subprocess.run(
        [_ffmpeg(), "-y", "-i", str(mp3), "-ar", "48000", "-ac", "1", str(output_wav)],
        capture_output=True, creationflags=_NO_WINDOW, timeout=timeout)
    mp3.unlink(missing_ok=True)
    if conv.returncode != 0 or not output_wav.exists():
        raise RuntimeError(f"ffmpeg falhou convertendo o áudio da ElevenLabs: "
                           f"{conv.stderr.decode(errors='replace')[-300:]}")
    with wave.open(str(output_wav), "rb") as w:
        return w.getnframes() / float(w.getframerate())
