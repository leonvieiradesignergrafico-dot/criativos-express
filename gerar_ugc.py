"""Criativos Express — orquestrador HEADLESS do vídeo UGC (Google Veo).

Espelha o espírito do gerar.py (lote de imagem), mas para VÍDEO: roda a esteira
COMPLETA sem GUI/threads de servidor, chamando as funções dos módulos do pipeline
direto e em sequência, uma variação por vez:

    roteiro (claude, grátis)  ->  keyframes (codex, grátis)
      ->  clipes (Google Veo, PAGO ~US$0,40/cena de 8s no veo_lite)  ->  montagem (ffmpeg, grátis)

Uso:
    python gerar_ugc.py <produto> [--n 2] [--modelo veo_lite]
                        [--modelo-texto sonnet] [--max-cenas N]
                        [--copy "texto"] [--avatar nome] [--pessoa-tipo avatar|influenciador]
                        [--legendas] [--json]

- <produto>: id da pasta em products/ (aceita o formato agrupado "cliente~produto").
- --n: quantas variações de vídeo gerar (cada uma é um roteiro/vídeo próprio). Padrão 2.
- --modelo: modelo do Veo (veo_lite | veo_fast | veo_quality). Padrão veo_lite (o mais barato).
- --max-cenas: corta o roteiro nas N primeiras cenas ANTES de animar (controle de custo;
  0 = todas). Ex.: teste barato com --n 1 --max-cenas 1 => 1 clipe Veo só.
- --copy: copy do anúncio; se ausente, usa output/copies.md e, na falta, o config.md.

Best-effort: erro numa cena não derruba o lote (o clipes.py já tem retry por cena);
erro numa variação não derruba as outras. Ao final imprime os caminhos dos .mp4 e um
JSON de status. Os vídeos finais são copiados para products/<produto>/output/ugc/.

Reaproveita 100% dos módulos do pipeline do app (roteiro/keyframes/clipes/montagem e o
veo_backend) — nada de Veo é reimplementado aqui.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import (atomic_write_json, carregar_config, ler_json,  # noqa: E402
                       product_dir, video_dir)
from app.pipeline import roteiro as roteiro_mod  # noqa: E402
from app.pipeline import keyframes as keyframes_mod  # noqa: E402
from app.pipeline import clipes as clipes_mod  # noqa: E402
from app.pipeline import montagem as montagem_mod  # noqa: E402


def _copy_do_produto(produto: str, copy_cli: str | None) -> tuple[str, str]:
    """Descobre a copy do anúncio (fonte única de verdade para o roteirista).

    Prioridade: --copy > output/copies.md > config.md. Retorna (copy, fonte)."""
    if copy_cli and copy_cli.strip():
        return copy_cli.strip(), "cli"
    p = product_dir(produto)
    copies = p / "output" / "copies.md"
    if copies.exists():
        txt = copies.read_text(encoding="utf-8", errors="replace").strip()
        if txt:
            return txt, "copies.md"
    cfg = p / "config.md"
    if cfg.exists():
        txt = cfg.read_text(encoding="utf-8", errors="replace").strip()
        if txt:
            return txt, "config.md"
    return f"Anúncio UGC do produto {produto}.", "fallback"


def _patch_veo_model(veo_model: str) -> None:
    """Faz o clipes.py usar o modelo Veo pedido no --modelo, SEM tocar no config.toml.
    O clipes lê modelo_veo de carregar_config(); envolvemos essa função em memória."""
    orig = clipes_mod.carregar_config

    def _patched():
        cfg = orig()
        cfg.setdefault("video", {})["modelo_veo"] = veo_model
        return cfg

    clipes_mod.carregar_config = _patched


def _trim_cenas(produto: str, vid: str, max_cenas: int) -> int:
    """Corta o roteiro.json nas primeiras `max_cenas` cenas (controle de custo).
    Retorna o nº de cenas resultante. max_cenas<=0 = não corta."""
    d = video_dir(produto, vid)
    rot_file = d / "roteiro.json"
    rot = ler_json(rot_file)
    cenas = rot.get("cenas") or []
    if max_cenas and max_cenas > 0 and len(cenas) > max_cenas:
        rot["cenas"] = cenas[:max_cenas]
        atomic_write_json(rot_file, rot)
        return max_cenas
    return len(cenas)


def _preco_clipe(veo_model: str) -> float:
    precos = (carregar_config().get("video", {}).get("precos_usd") or {})
    return float(precos.get(veo_model, 0.75))


def gerar_uma(produto: str, copy: str, idx: int, *, veo_model: str,
              modelo_texto: str | None, max_cenas: int, avatar: str | None,
              pessoa_tipo: str, legendas: bool, out_ugc: Path) -> dict:
    """Roda a esteira COMPLETA para UMA variação. Best-effort: captura o erro e
    devolve o que conseguiu (nunca levanta — o lote continua)."""
    res: dict = {"variacao": idx, "vid": None, "cenas": 0, "clipes_ok": 0,
                 "mp4": None, "erro": None, "erros_cena": []}
    t0 = time.time()
    try:
        # Nudge de diversidade entre variações (gancho de abertura distinto por vídeo).
        copy_v = copy if idx == 1 else (
            copy + f"\n\n[Variação {idx}: abra com um GANCHO diferente das outras variações, "
                   "mesma oferta e mesma verdade.]")

        # 1) Roteiro (claude bridge, grátis) -> videos/<produto>/<vid>/roteiro.json
        print(f"[var {idx}] roteiro…", flush=True)
        roteiro = roteiro_mod.criar_roteiro(produto, copy_v, avatar, modelo=modelo_texto,
                                            pessoa_tipo=pessoa_tipo)
        vid = roteiro["id"]
        res["vid"] = vid

        # 2) Corte de custo (opcional): fica só nas N primeiras cenas.
        n_cenas = _trim_cenas(produto, vid, max_cenas)
        res["cenas"] = n_cenas
        print(f"[var {idx}] vid={vid} cenas={n_cenas}", flush=True)

        # 3) Keyframes (codex, grátis) — best-effort por cena.
        print(f"[var {idx}] keyframes…", flush=True)
        keyframes_mod.gerar_keyframes(produto, vid)

        # 4) Clipes via Veo (PAGO) — best-effort por cena (retry vive no clipes.py).
        print(f"[var {idx}] clipes (Veo {veo_model})…", flush=True)
        clipes_mod.gerar_clipes(produto, vid)

        d = video_dir(produto, vid)
        rot = ler_json(d / "roteiro.json") or {}
        cenas = rot.get("cenas") or []
        res["clipes_ok"] = sum(1 for c in cenas if c.get("clipe", {}).get("gerado"))
        res["erros_cena"] = [{"n": c["n"], "erro": c["clipe"].get("erro")}
                             for c in cenas if c.get("clipe", {}).get("erro")]

        if res["clipes_ok"] == 0:
            res["erro"] = "Nenhum clipe do Veo foi gerado (ver erros_cena)."
            return res

        # 5) Montagem final (ffmpeg, grátis) -> videos/<produto>/<vid>/final/video.mp4
        print(f"[var {idx}] montagem…", flush=True)
        final = montagem_mod.montar(produto, vid, legendas=legendas)

        # 6) Publica no local padrão de saída do produto: output/ugc/<vid>.mp4
        out_ugc.mkdir(parents=True, exist_ok=True)
        destino = out_ugc / f"{vid}.mp4"
        shutil.copy2(final, destino)
        res["mp4"] = str(destino)
        print(f"[var {idx}] OK -> {destino}", flush=True)
    except Exception as e:  # noqa: BLE001 — best-effort: uma variação não derruba o lote
        res["erro"] = f"{type(e).__name__}: {e}"
        print(f"[var {idx}] ERRO: {res['erro']}", flush=True)
    finally:
        res["segundos"] = round(time.time() - t0, 1)
    return res


def gerar_ugc(produto: str, *, n: int = 2, veo_model: str = "veo_lite",
              modelo_texto: str | None = None, max_cenas: int = 0,
              copy_cli: str | None = None, avatar: str | None = None,
              pessoa_tipo: str = "avatar", legendas: bool = False) -> dict:
    """Gera N vídeos UGC do produto, sequencialmente. Retorna o status consolidado."""
    product_dir(produto)  # valida cedo (levanta se o produto não existe)
    if veo_model not in {"veo_lite", "veo_fast", "veo_quality"} and not veo_model.startswith("veo-"):
        veo_model = "veo_lite"
    _patch_veo_model(veo_model)

    copy, fonte = _copy_do_produto(produto, copy_cli)
    out_ugc = product_dir(produto) / "output" / "ugc"

    print(f"UGC headless: produto={produto} n={n} veo={veo_model} "
          f"max_cenas={max_cenas or 'todas'} copy={fonte}", flush=True)

    variacoes = []
    for i in range(1, max(1, int(n)) + 1):
        variacoes.append(gerar_uma(
            produto, copy, i, veo_model=veo_model, modelo_texto=modelo_texto,
            max_cenas=max_cenas, avatar=avatar, pessoa_tipo=pessoa_tipo,
            legendas=legendas, out_ugc=out_ugc))

    mp4s = [v["mp4"] for v in variacoes if v.get("mp4")]
    clipes_pagos = sum(v.get("clipes_ok", 0) for v in variacoes)
    status = {
        "produto": produto,
        "veo_model": veo_model,
        "copy_fonte": fonte,
        "solicitados": n,
        "concluidos": len(mp4s),
        "mp4s": mp4s,
        "clipes_veo_gerados": clipes_pagos,
        "custo_estimado_usd": round(clipes_pagos * _preco_clipe(veo_model), 2),
        "variacoes": variacoes,
        "out_dir": str(out_ugc),
    }
    return status


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Gera vídeos UGC (Veo) em lote, headless.")
    ap.add_argument("produto", help="pasta do produto em products/ (aceita cliente~produto)")
    ap.add_argument("--n", type=int, default=2, help="quantas variações de vídeo (padrão 2)")
    ap.add_argument("--modelo", default="veo_lite", help="modelo Veo: veo_lite|veo_fast|veo_quality")
    ap.add_argument("--modelo-texto", default=None, help="modelo do roteirista (claude): sonnet|opus|…")
    ap.add_argument("--max-cenas", type=int, default=0, help="corta o roteiro nas N 1ªs cenas (0=todas)")
    ap.add_argument("--copy", default=None, help="copy do anúncio (senão usa copies.md/config.md)")
    ap.add_argument("--avatar", default=None, help="pessoa que aparece (opcional; senão b-roll de produto)")
    ap.add_argument("--pessoa-tipo", default="avatar", choices=["avatar", "influenciador"])
    ap.add_argument("--legendas", action="store_true", help="queima legendas UGC na montagem")
    ap.add_argument("--json", action="store_true", help="imprime só o JSON de status no final")
    args = ap.parse_args(argv)

    status = gerar_ugc(
        args.produto, n=args.n, veo_model=args.modelo, modelo_texto=args.modelo_texto,
        max_cenas=args.max_cenas, copy_cli=args.copy, avatar=args.avatar,
        pessoa_tipo=args.pessoa_tipo, legendas=args.legendas)

    print("\n===== UGC CONCLUÍDO =====", flush=True)
    for mp4 in status["mp4s"]:
        print(f"MP4: {mp4}", flush=True)
    print(f"Concluídos: {status['concluidos']}/{status['solicitados']} | "
          f"clipes Veo: {status['clipes_veo_gerados']} | "
          f"custo est.: US${status['custo_estimado_usd']}", flush=True)
    print("STATUS_JSON: " + json.dumps(status, ensure_ascii=False), flush=True)
    # Código 0 se ao menos um vídeo saiu; 1 se nenhum (o chamador decide o que fazer).
    return 0 if status["concluidos"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
