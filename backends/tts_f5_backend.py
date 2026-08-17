"""TTS local F5-TTS PT-BR (Fase 4) — roda num venv separado com GPU.

Enquanto o venv não estiver configurado ([local].python vazio ou sem f5-tts),
falha com mensagem clara; use engine "edge" no voz.json do avatar.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def sintetizar(texto: str, output_wav, voz: dict, timeout: int = 300,
               cancel_event=None) -> float:
    from workspace import carregar_config
    py = (carregar_config().get("local", {}).get("python") or "").strip()
    if not py or not Path(py).exists():
        raise RuntimeError("F5-TTS local não instalado (ver scripts/instalar_wan.md). "
                           "Use engine 'edge' na voz do avatar.")
    output_wav = Path(output_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    ref_audio = (voz or {}).get("ref_audio")
    ref_text = (voz or {}).get("ref_text") or ""
    cmd = [py, "-m", "f5_tts.infer.infer_cli",
           "--model", "F5-TTS", "--gen_text", texto,
           "--output_file", str(output_wav)]
    if ref_audio:
        cmd += ["--ref_audio", str(ref_audio), "--ref_text", ref_text]
    r = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW, timeout=timeout)
    if r.returncode != 0 or not output_wav.exists():
        raise RuntimeError(f"F5-TTS falhou: {r.stderr.decode(errors='replace')[-400:]}")
    with wave.open(str(output_wav), "rb") as w:
        return w.getnframes() / float(w.getframerate())
