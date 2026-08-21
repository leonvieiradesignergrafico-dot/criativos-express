#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orquestrador do auto-cadastro (Fase 1 / Fase 3).

DESCOBERTA DE CLIENTES (padrão): consulta /api/meta/accounts no Dashboard, que lê
do BANCO o mapa cliente -> conta(s) de anúncio (funnels.meta_ad_account_id) — o
MESMO mapa das métricas de todos os clientes. Assim roda pra TODOS os clientes que
o Dashboard conhece SEM depender de preencher clients/<slug>/contexto.md.

FALLBACK: se o endpoint não responder (sem rede/sem key/fora do ar), cai na lista
de clients/<slug>/contexto.md (elegível = tem act_id, não é STUB <TODO>), com aviso.

Dispara 1 worker por cliente EM PARALELO (multiprocessing), varrendo todas as
act_ids de cada um, e agrega products/_auto-cadastro/<data>_resumo.json.

Uso:
  python run.py --cliente leon --dry-run         # 1 cliente só (prova)
  python run.py --dry-run                         # TODOS (descoberta via banco)
  python run.py --transcribe                      # TODOS, com transcrição de vídeo
  python run.py --list                            # só lista o que rodaria
  python run.py --fixture-accounts fake.json ...  # testa a descoberta sem rede
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from multiprocessing import Pool
from pathlib import Path

# Import robusto (roda como módulo do pacote OU como script solto).
try:
    from . import worker as W
except Exception:  # noqa: BLE001
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import worker as W  # type: ignore


def _run_one(payload: tuple[str, dict]) -> dict:
    slug, opts = payload
    try:
        return W.run_client(slug, opts)
    except Exception as e:  # noqa: BLE001
        return {"cliente": slug, "ok": False, "eligible": True,
                "products": [], "conflicts": [], "errors": [f"worker crash: {e}"],
                "total_ads": 0, "sem_pagina": 0, "act_ids": []}


def discover_clients(base: str, key: str, fixture_accounts: str | None) -> tuple[list[dict], str, str]:
    """Descobre clientes+contas. Retorna (clients, source, warning).

    Ordem: --fixture-accounts (teste) -> endpoint /api/meta/accounts (banco) ->
    fallback clients/<slug>/contexto.md. Cada cliente vira
    {slug, nome, act_ids:[...], business_id}.
    """
    # 1) fixture (teste offline)
    if fixture_accounts:
        raw = json.loads(Path(fixture_accounts).read_text(encoding="utf-8"))
        clients = raw.get("clients", raw) if isinstance(raw, dict) else raw
        return _norm_clients(clients), "fixture", ""

    # 2) endpoint (banco) — só se tiver key
    if key:
        try:
            clients = W.fetch_accounts(base, key)
            return _norm_clients(clients), "banco", ""
        except Exception as e:  # noqa: BLE001
            warn = f"descoberta via banco falhou ({e}) — usando fallback contexto.md"
    else:
        warn = "sem DEUROI_KEY/CRON_KEY — usando fallback contexto.md"

    # 3) fallback contexto.md
    ctx = [c for c in W.list_eligible_clients() if c["eligible"]]
    clients = [{"slug": c["slug"], "nome": c["slug"], "act_ids": c["act_ids"],
                "business_id": c.get("business_id")} for c in ctx]
    return clients, "contexto.md", warn


def _norm_clients(clients: list) -> list[dict]:
    """Normaliza a resposta do endpoint/fixture pro formato interno, só com act_ids."""
    out = []
    for c in clients or []:
        if not isinstance(c, dict):
            continue
        acts = [str(a).strip() for a in (c.get("act_ids") or []) if str(a).strip()]
        if not acts:
            continue
        out.append({
            "slug": c.get("slug") or W.slugify(c.get("nome", "cliente")),
            "nome": c.get("nome") or c.get("slug") or "cliente",
            "act_ids": acts,
            "business_id": c.get("business_id"),
        })
    return out


def build_opts(args) -> dict:
    """Mesmas opções do worker, montadas a partir do .env + flags."""
    env = W.load_env()
    base, key = W.dashboard_config(env)
    dry = args.dry_run
    return {
        "base_url": base,
        "key": key,
        "status": args.status,
        "fixture": None,       # orquestrador não usa fixture (é caminho de rede)
        "dry_run": dry,
        "fetch_page": not args.no_page,
        "download_images": not args.no_images,
        "transcribe": args.transcribe and not dry,
        "follow_redirects": args.follow_redirects,
        "write": not args.no_write,
        "gen_date": date.today().isoformat(),
    }


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Auto-cadastro — orquestrador N-clientes")
    ap.add_argument("--cliente", default=None, help="roda só este slug (prova da Fase 1)")
    ap.add_argument("--dry-run", action="store_true", help="não transcreve (prepara só)")
    ap.add_argument("--status", default=None, help="filtro Meta effective_status")
    ap.add_argument("--transcribe", action="store_true")
    ap.add_argument("--follow-redirects", action="store_true")
    ap.add_argument("--no-page", action="store_true")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--workers", type=int, default=4, help="paralelismo (default 4)")
    ap.add_argument("--list", action="store_true", help="só lista o que rodaria e sai")
    ap.add_argument("--fixture-accounts", default=None,
                    help="JSON local simulando /api/meta/accounts (testa a descoberta sem rede)")
    args = ap.parse_args(argv)

    opts = build_opts(args)

    # Descobre clientes+contas (banco por padrão; fixture/contexto.md como alternativas).
    clients, source, warn = discover_clients(opts["base_url"], opts["key"], args.fixture_accounts)
    if warn:
        print(f"[auto-cadastro] AVISO: {warn}")

    if args.cliente:
        clients = [c for c in clients if c["slug"] == args.cliente]
        if not clients:
            print(f"cliente '{args.cliente}' não encontrado na descoberta ({source}). "
                  f"Confira o slug ou o mapa de contas do Dashboard.")
            return 1

    if args.list:
        print(f"CLIENTES (fonte={source}):")
        for c in clients:
            bid = c.get("business_id") or "n/d"
            print(f"  + {c['slug']} ({c['nome']}): act_ids={c['act_ids']} business_id={bid}")
        return 0

    print(f"[auto-cadastro] fonte={source}: {len(clients)} cliente(s). "
          f"dry_run={opts['dry_run']} transcribe={opts['transcribe']}")

    # cada worker recebe suas act_ids injetadas (não relê contexto.md)
    payloads = []
    for c in clients:
        c_opts = dict(opts)
        c_opts["act_ids"] = c["act_ids"]
        c_opts["act_source"] = source
        payloads.append((c["slug"], c_opts))
    results: list[dict] = []
    if len(payloads) <= 1:
        for p in payloads:
            results.append(_run_one(p))
    else:
        with Pool(processes=min(args.workers, len(payloads))) as pool:
            results = pool.map(_run_one, payloads)

    # --- agrega índice ---
    out_dir = W.PRODUCTS_DIR / "_auto-cadastro"
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {
        "gen_date": opts["gen_date"],
        "dry_run": opts["dry_run"],
        "fonte_descoberta": source,
        "clientes": len(results),
        "resumo": [],
    }
    total_products = 0
    total_conflicts = 0
    for r in results:
        prods = r.get("products", [])
        created = sum(1 for p in prods if p.get("action") == "created")
        updated = sum(1 for p in prods if p.get("action") == "updated")
        total_products += created + updated
        total_conflicts += len(r.get("conflicts", []))
        index["resumo"].append({
            "cliente": r.get("cliente"),
            "ok": r.get("ok"),
            "total_ads": r.get("total_ads", 0),
            "produtos_novos": created,
            "produtos_atualizados": updated,
            "conflitos": r.get("conflicts", []),
            "sem_pagina": r.get("sem_pagina", 0),
            "erros": r.get("errors", []),
            "produtos": [{"slug": p["slug"], "action": p["action"],
                          "ads": p["ads"], "flags": p["flags"]} for p in prods],
        })

    out_file = out_dir / f"{opts['gen_date']}_resumo.json"
    out_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[auto-cadastro] concluído: {total_products} rascunho(s), "
          f"{total_conflicts} conflito(s). Índice: {out_file}")
    for r in results:
        tag = "OK" if r.get("ok") else "FALHOU"
        print(f"  [{tag}] {r.get('cliente')}: ads={r.get('total_ads',0)} "
              f"produtos={len(r.get('products', []))} erros={len(r.get('errors', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
