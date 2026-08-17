"""Etapa 3: narração por cena (TTS grátis), voz fixa por avatar."""
from __future__ import annotations

from pathlib import Path

from workspace import atomic_write_json, carregar_config, ler_json, pessoa_dir


def voz_do_avatar(avatar: str | None, pessoa_tipo: str = "avatar") -> dict:
    cfg = carregar_config().get("voz", {})
    padrao = {"engine": cfg.get("engine", "eleven"),
              "edge_voice": cfg.get("voz_padrao", "pt-BR-FranciscaNeural"), "rate": "+0%",
              # ElevenLabs (engine="eleven"): repassa voice_id/modelo/ajustes do config
              "voice_id": cfg.get("voice_id"),
              "model_id": cfg.get("eleven_model", "eleven_multilingual_v2"),
              "stability": cfg.get("stability", 0.4),
              "similarity": cfg.get("similarity", 0.75),
              "style": cfg.get("style", 0.0)}
    if not avatar:
        return padrao
    try:
        v = ler_json(pessoa_dir(avatar, pessoa_tipo) / "voz" / "voz.json")
    except ValueError:  # pessoa sem pasta (nome inválido) — usa a voz padrão do config
        v = None
    return {**padrao, **(v or {})}


def _backend(voz: dict):
    engine = (voz.get("engine") or "edge").lower()
    if engine == "f5":
        from backends import tts_f5_backend as be
    elif engine == "eleven":
        from backends import tts_eleven_backend as be
    else:
        from backends import tts_edge_backend as be
    return be


def sintetizar_cena(roteiro: dict, cena: dict, audio_dir: Path, cancel_event=None) -> tuple[str, float]:
    """Gera audio/cena_NN.wav para a narração da cena. Retorna (nome, duração_s)."""
    voz = voz_do_avatar(roteiro.get("avatar"), roteiro.get("pessoa_tipo", "avatar"))
    out = audio_dir / f"cena_{cena['n']:02d}.wav"
    dur = _backend(voz).sintetizar(cena["narracao"], out, voz, cancel_event=cancel_event)
    return out.name, dur


def preview_voz(texto: str, voz: dict, out_wav: Path) -> Path:
    _backend(voz).sintetizar(texto, out_wav, voz)
    return out_wav
