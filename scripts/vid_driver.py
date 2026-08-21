"""Driver headless para gerar vídeo UGC sem a GUI.
Uso:
  python scripts/vid_driver.py roteiro "<copy>" [avatar]      -> cria roteiro + keyframes (gratis)
  python scripts/vid_driver.py finalizar <vid>                -> clipes (fal, pago) + montar mp4
"""
import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# Carrega o .env no ambiente (ELEVEN_API_KEY, FAL_KEY, etc.) antes de importar o app.
def _load_env():
    envf = os.path.join(ROOT, ".env")
    if not os.path.exists(envf):
        return
    for line in open(envf, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                os.environ[k.strip()] = v
_load_env()

from app.pipeline import roteiro as roteiro_mod
from app.pipeline import keyframes as keyframes_mod
from app.pipeline import clipes as clipes_mod
from app.pipeline import montagem as montagem_mod
from workspace import video_dir, ler_json

PRODUTO = "Bolo Iohanna"

def main():
    acao = sys.argv[1]
    if acao == "roteiro":
        copy = sys.argv[2]
        avatar = sys.argv[3] if len(sys.argv) > 3 else "Bru"
        print(f"[roteiro] produto={PRODUTO} avatar={avatar}", flush=True)
        rot = roteiro_mod.criar_roteiro(PRODUTO, copy, avatar)
        vid = rot["id"]
        print(f"[roteiro] VID={vid}  cenas={len(rot['cenas'])}", flush=True)
        for c in rot["cenas"]:
            print(f"   cena {c['n']} [{c.get('tipo')}]: {str(c.get('narracao',''))[:90]}", flush=True)
        print("[keyframes] gerando (gratis)...", flush=True)
        keyframes_mod.gerar_keyframes(PRODUTO, vid)
        rot = ler_json(video_dir(PRODUTO, vid) / "roteiro.json")
        feitos = sum(1 for c in rot["cenas"] if c["keyframe"]["arquivo"])
        print(f"[keyframes] OK: {feitos}/{len(rot['cenas'])} keyframes. VID={vid}", flush=True)
    elif acao == "finalizar":
        vid = sys.argv[2]
        motor = sys.argv[3] if len(sys.argv) > 3 else "veo"
        # reset do estado de clipe (slideshow/tentativas antigas marcaram gerado=True)
        d0 = video_dir(PRODUTO, vid)
        rot0 = ler_json(d0 / "roteiro.json")
        for c in rot0["cenas"]:
            c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                          "erro": None, "lipsync_aplicado": False}
        from workspace import atomic_write_json as _awj
        _awj(d0 / "roteiro.json", rot0)
        print(f"[clipes] animando (motor={motor})... VID={vid}", flush=True)
        clipes_mod.gerar_clipes(PRODUTO, vid, motor=motor)
        # relatório por cena
        rot = ler_json(video_dir(PRODUTO, vid) / "roteiro.json")
        for c in rot["cenas"]:
            cl = c.get("clipe", {})
            print(f"   cena {c['n']}: gerado={cl.get('gerado')} erro={str(cl.get('erro'))[:120]}", flush=True)
        print("[montar] montando mp4...", flush=True)
        caminho = montagem_mod.montar(PRODUTO, vid, legendas=True)
        print(f"[final] MP4: {caminho}", flush=True)
    else:
        print("acao invalida", flush=True); sys.exit(1)

if __name__ == "__main__":
    main()
