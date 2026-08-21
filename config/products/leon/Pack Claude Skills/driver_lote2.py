import json, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path.cwd()))
from backends import codex_backend as be

prod = Path("products/pack-claude-skills")
out = prod/"output"/"criativos_lote2"; out.mkdir(parents=True, exist_ok=True)
prompts = json.loads((prod/"output"/"prompts_lote2.json").read_text(encoding="utf-8"))
ANEX = "Nao ha imagens anexadas; gere a imagem inteiramente a partir do briefing de texto abaixo."

def gen(p):
    dest = out/(p["id"]+".png")
    t0=time.time()
    try:
        be.generate(p["prompt"], [], dest, size="1024x1024", timeout=600,
                    reasoning="low", anexos_desc=ANEX)
        return f"OK {p['id']} ({round(time.time()-t0)}s)"
    except Exception as e:
        return f"FALHA {p['id']}: {str(e)[:200]}"

with ThreadPoolExecutor(max_workers=3) as ex:
    futs=[ex.submit(gen,p) for p in prompts]
    for f in as_completed(futs):
        print(f.result(), flush=True)
print("=== FIM ===", flush=True)
