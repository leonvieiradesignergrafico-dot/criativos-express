"""Criativos Express — geração de imagens em lote.

Lê products/<produto>/output/prompts.json e gera 1 imagem por entrada, sempre
anexando as fotos de products/<produto>/referencia/ para manter o produto IDÊNTICO.

Backend padrão: Codex (plano ChatGPT, grátis). Alternativa: API paga (gpt-image-2).

Uso:
    python gerar.py <produto> [--backend codex|api]
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCTS = ROOT / "products"

# Formatos aceitos diretamente como referência pelo gpt-image-2 / Codex.
FORMATOS_OK = {".png", ".jpg", ".jpeg", ".webp"}
# Formatos que precisam ser convertidos antes (via ffmpeg).
FORMATOS_CONVERTER = {".avif", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff"}

# Regra de fidelidade injetada em TODO prompt (a regra absoluta do projeto).
PREFIXO_FIDELIDADE = (
    "REGRA ABSOLUTA DE FIDELIDADE AO PRODUTO: o produto no criativo deve ser IDÊNTICO "
    "às imagens de referência anexadas — mesmo formato, cor, material, tampa, logotipo, "
    "textos/rótulos e proporções reais. NÃO invente rótulos, números ou textos diferentes "
    "dos reais. Você pode alterar APENAS ângulo, iluminação, fundo e ambientação, mantendo "
    "tudo fotorrealista e coerente com o produto real."
)


def carregar_config() -> dict:
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def coletar_referencias(product_dir: Path) -> list[Path]:
    """Retorna até 16 fotos de referência utilizáveis (convertendo formatos quando preciso)."""
    ref_dir = product_dir / "referencia"
    if not ref_dir.exists():
        return []
    cache = product_dir / "output" / ".refs"
    refs: list[Path] = []
    # Prioriza formatos já aceitos; evita duplicar o mesmo produto (mesmo nome-base).
    arquivos = [p for p in sorted(ref_dir.iterdir())
                if p.is_file() and p.name != ".gitkeep"]
    stems_ok = {p.stem.lower() for p in arquivos if p.suffix.lower() in FORMATOS_OK}
    for p in arquivos:
        ext = p.suffix.lower()
        if ext in FORMATOS_OK:
            refs.append(p)
        elif ext in FORMATOS_CONVERTER and p.stem.lower() not in stems_ok:
            cache.mkdir(parents=True, exist_ok=True)
            destino = cache / (p.stem + ".png")
            if not destino.exists():
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(p), str(destino)],
                    capture_output=True,
                )
            if destino.exists():
                refs.append(destino)
    return refs[:16]


def gerar_criativos(produto: str, backend: str | None = None, on_progress=None) -> dict:
    """Gera todos os criativos de um produto. Retorna o status final.

    on_progress(status_dict) é chamado a cada atualização (usado pelo painel).
    """
    cfg = carregar_config()["geracao"]
    backend = backend or cfg.get("backend", "codex")
    size = cfg.get("size", "1024x1024")
    quality = cfg.get("quality", "high")
    timeout = int(cfg.get("timeout", 300))

    product_dir = PRODUCTS / produto
    prompts_file = product_dir / "output" / "prompts.json"
    if not prompts_file.exists():
        raise FileNotFoundError(
            f"Não achei {prompts_file}. Rode a skill /gerar-prompts-imagem antes."
        )

    entradas = json.loads(prompts_file.read_text(encoding="utf-8"))
    if isinstance(entradas, dict) and "criativos" in entradas:
        entradas = entradas["criativos"]

    referencias = coletar_referencias(product_dir)
    if not referencias:
        raise RuntimeError(
            f"Nenhuma foto de referência em {product_dir / 'referencia'}. "
            "A referência do produto é obrigatória."
        )

    out_dir = product_dir / "output" / "criativos"
    out_dir.mkdir(parents=True, exist_ok=True)
    status_file = out_dir / "status.json"

    status = {
        "produto": produto,
        "backend": backend,
        "total": len(entradas),
        "feitos": 0,
        "atual": None,
        "arquivos": [],
        "erros": [],
        "em_andamento": True,
    }

    def salvar():
        status_file.write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if on_progress:
            on_progress(dict(status))

    salvar()

    if backend == "api":
        from backends import api_backend as be

        def gerar_um(prompt, out_file):
            return be.generate(prompt, referencias, out_file, size=size,
                               quality=quality, timeout=timeout)
    else:
        from backends import codex_backend as be

        def gerar_um(prompt, out_file):
            return be.generate(prompt, referencias, out_file, size=size,
                               timeout=timeout, workdir=str(out_dir))

    for i, entrada in enumerate(entradas):
        cid = str(entrada.get("id") or f"criativo_{i + 1:02d}")
        status["atual"] = cid
        salvar()

        tamanho = entrada.get("tamanho", size)
        prompt = (
            f"{PREFIXO_FIDELIDADE}\n\n{entrada.get('prompt', '')}\n\n"
            f"Formato/tamanho: {tamanho}, fotorrealista."
        )
        out_file = out_dir / f"{cid}.png"
        try:
            gerar_um(prompt, out_file)
            status["arquivos"].append(out_file.name)
        except Exception as e:  # noqa: BLE001
            status["erros"].append({"id": cid, "erro": str(e)})

        status["feitos"] += 1
        salvar()

    status["atual"] = None
    status["em_andamento"] = False
    salvar()
    return status


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Gera criativos em lote.")
    ap.add_argument("produto", help="nome da pasta do produto em products/")
    ap.add_argument("--backend", choices=["codex", "api"], default=None)
    args = ap.parse_args(argv)

    def progresso(s):
        atual = s["atual"] or "-"
        print(f"[{s['feitos']}/{s['total']}] gerando: {atual}")

    res = gerar_criativos(args.produto, backend=args.backend, on_progress=progresso)
    print(f"\nConcluído: {len(res['arquivos'])} criativos, {len(res['erros'])} erros.")
    if res["erros"]:
        for e in res["erros"]:
            print(f"  ERRO {e['id']}: {e['erro'][:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
