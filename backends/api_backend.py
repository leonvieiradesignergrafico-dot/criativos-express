"""Backend de geração via API OpenAI gpt-image-2 (PAGO — fallback opcional).

Usa o endpoint de edição com as fotos de referência (alta fidelidade automática).
Requer OPENAI_API_KEY no ambiente (.env).
"""
from __future__ import annotations

import base64
from pathlib import Path


def generate(
    prompt: str,
    reference_paths: list,
    output_path,
    size: str = "1024x1024",
    quality: str = "high",
    timeout: int = 300,
    **_ignored,
) -> str:
    """Gera 1 imagem e a salva em output_path. Levanta exceção em caso de falha."""
    from openai import OpenAI

    output_path = Path(output_path)
    client = OpenAI(timeout=timeout)

    arquivos = [open(str(r), "rb") for r in reference_paths]
    try:
        # NÃO passar input_fidelity: o gpt-image-2 usa alta fidelidade automaticamente.
        resultado = client.images.edit(
            model="gpt-image-2",
            image=arquivos,
            prompt=prompt,
            size=size,
            quality=quality,
        )
    finally:
        for f in arquivos:
            f.close()

    b64 = resultado.data[0].b64_json
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(b64))
    return str(output_path)
