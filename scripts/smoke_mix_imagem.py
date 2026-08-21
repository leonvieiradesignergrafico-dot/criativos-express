"""Smoke do MIX de imagem: seta 3 formatos e chama /api/chat, conferindo que as
copies voltam taggeadas com formatos diferentes. Não gera imagem (só copy)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.argv = ["x"]
import app.server as s

PRODUTO = "juan~X-tune Plugin"
c = s.app.test_client()
# seta o mix
s._escrever_formatos(PRODUTO, ["padrao", "wikihow", "noticia"])
print("formatos:", s._ler_formatos(PRODUTO))
r = c.post("/api/chat", json={"produto": PRODUTO,
           "mensagem": "quero copies pra vender o plugin de mixagem de vocal",
           "modelo": "sonnet"})
d = json.loads(r.data)
if not d.get("ok"):
    print("ERRO:", d.get("erro")); sys.exit(1)
copies = d.get("copies") or []
from collections import Counter
print("total copies:", len(copies))
print("por formato:", dict(Counter(c.get("formato") for c in copies)))
for cp in copies[:8]:
    print(f"  [{cp.get('formato')}] {cp.get('id')}: {str(cp.get('headline'))[:60]}")
# restaura
s._escrever_formatos(PRODUTO, ["padrao"])
print("MIX IMAGEM SMOKE OK")
