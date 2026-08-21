import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.argv = ["x"]
import app.server  # noqa
from app.pipeline import formatos_video as fv
from app.pipeline import roteiro

B = "```roteiro-json"
E = "```"

def bloco(elenco=None, narr="oi"):
    el = f',"elenco":"{elenco}"' if elenco else ""
    return B + '\n{"cenas":[{"n":1,"tipo":"avatar_fala"' + el + ',"narracao":"' + narr + '"}]}\n' + E

assert fv.multi_pessoa("experimento_social") and fv.multi_pessoa("corte_podcast"), "multi_pessoa nao marcado"
assert fv.multi_pessoa("dialogo") and fv.multi_pessoa("entrevista") and fv.multi_pessoa("esquete")
assert not fv.multi_pessoa("depoimento") and not fv.multi_pessoa("top5"), "depoimento/top5 nao sao multi"
assert fv.diretiva("padrao") == "" and fv.roteirista_cerebro("padrao") == open(
    "app/prompts/roteirista_ugc.md", encoding="utf-8").read(), "regressao padrao"

c = roteiro.extrair_cenas(bloco("B"), digital=False, multi_pessoa=False)
assert c[0]["elenco"] == "A", "enforcement single-person falhou"
c = roteiro.extrair_cenas(bloco("B"), digital=False, multi_pessoa=True)
assert c[0]["elenco"] == "B", "multi deveria manter B"
c = roteiro.extrair_cenas(bloco(None, "compre — agora - ja"), multi_pessoa=False)
assert "—" not in c[0]["narracao"] and " - " not in c[0]["narracao"], "travessao/hifen na narracao"
print("FUNCIONAL OK:", repr(c[0]["narracao"]))
