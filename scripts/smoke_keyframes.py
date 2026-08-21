"""Gera keyframes (GRÁTIS, codex) de um roteiro já criado e, opcionalmente, 1 clipe (Veo, PAGO).
Uso: python scripts/smoke_keyframes.py "<produto>" <vid> [--clipe N]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.argv_clean = list(sys.argv)
from workspace import video_dir, ler_json
from app.pipeline import keyframes as kf
from app.pipeline import clipes as cl

produto = sys.argv[1]
vid = sys.argv[2]
clipe_n = None
if "--clipe" in sys.argv:
    clipe_n = int(sys.argv[sys.argv.index("--clipe") + 1])

d = video_dir(produto, vid)
rot = ler_json(d / "roteiro.json")
print(f"produto={produto} vid={vid} formato={rot.get('formato_video')} cenas={len(rot.get('cenas') or [])}")
print("gerando keyframes (codex, gratis)...", flush=True)
kf.gerar_keyframes(produto, vid)
rot = ler_json(d / "roteiro.json")
for c in rot.get("cenas") or []:
    k = c.get("keyframe") or {}
    print(f"  cena {c['n']} [{c['tipo']}|{c.get('elenco','A')}]: keyframe={k.get('arquivo')} ")
if clipe_n is not None:
    print(f"gerando 1 clipe (Veo, PAGO) da cena {clipe_n}...", flush=True)
    cl.gerar_clipes(produto, vid, ns=[clipe_n])
    rot = ler_json(d / "roteiro.json")
    c = next((x for x in rot["cenas"] if x["n"] == clipe_n), None)
    print("  clipe:", (c or {}).get("clipe"))
print("KF SMOKE FEITO")
