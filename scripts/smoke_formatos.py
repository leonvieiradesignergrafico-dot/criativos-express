"""Smoke test: copy -> roteiro para formatos de video, sem gerar imagem/video.
Valida que o cerebro do formato produz cenas coerentes e no schema da esteira."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
FORMATOS = sys.argv[1:] if len(sys.argv) > 1 else ["top5", "dialogo"]
sys.argv = ["x"]  # neutraliza argv p/ os imports do app (depois de ler FORMATOS)
from app.pipeline import copy_ugc, roteiro as roteiro_mod
from app.pipeline import formatos_video as fv

PRODUTO = "iohanna~Bolo Iohanna"
AVATAR = "Bru"

for fmt in FORMATOS:
    print("\n" + "=" * 70)
    print(f"FORMATO: {fmt}  ({fv.info(fmt)['label']})  multi_pessoa={fv.multi_pessoa(fmt)}")
    print("=" * 70)
    try:
        r = copy_ugc.conversar(PRODUTO, f"Quero 1 roteiro no formato {fv.info(fmt)['label']} pra vender o bolo.",
                               modelo="sonnet", modo="ugc_depoimento", formato=fmt)
        op = (r.get("opcoes") or [None])[0]
        if not op:
            print("  [sem opcoes de copy]"); continue
        print("  COPY opcao:", (op.get("titulo") or "")[:70])
        copy_txt = json.dumps(op, ensure_ascii=False)
        rot = roteiro_mod.criar_roteiro(PRODUTO, copy_txt, AVATAR, modelo="sonnet",
                                        pessoa_tipo="avatar", formato_video=fmt)
        print(f"  formato_video salvo: {rot.get('formato_video')}  | cenas: {len(rot.get('cenas') or [])}")
        for c in rot.get("cenas") or []:
            el = c.get("elenco", "A")
            print(f"    cena {c['n']} [{c['tipo']}|{el}|{c['duracao_s']}s]: {c['narracao'][:70]}")
    except Exception as e:
        print("  ERRO:", str(e)[:300])
print("\nSMOKE FEITO")
