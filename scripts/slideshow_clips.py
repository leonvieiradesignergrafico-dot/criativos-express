"""Monta um vídeo UGC SEM fal: transforma cada keyframe num clipe de imagem
(com zoom sutil) na duração da narração, e usa o montar() pra mux de voz + legendas.
Uso: python scripts/slideshow_clips.py <vid>
"""
import sys, os, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)

def _load_env():
    envf = os.path.join(ROOT, ".env")
    if os.path.exists(envf):
        for line in open(envf, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); v = v.strip().strip('"').strip("'")
                if v: os.environ[k.strip()] = v
_load_env()

from workspace import video_dir, ler_json, atomic_write_json
from app.pipeline import montagem as montagem_mod

PRODUTO = "Bolo Iohanna"
FF = os.environ.get("FFMPEG", "ffmpeg")

def dur_wav(path):
    out = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                          "-of","default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try: return float(out.stdout.strip())
    except: return 4.0

def main():
    vid = sys.argv[1]
    d = video_dir(PRODUTO, vid)
    rot = ler_json(d / "roteiro.json")
    kf = d / "keyframes"; ad = d / "audio"; cl = d / "clipes"; cl.mkdir(exist_ok=True)
    for c in rot["cenas"]:
        n = c["n"]
        img = kf / (c["keyframe"]["arquivo"] or f"cena_{n:02d}.png")
        wav = ad / f"cena_{n:02d}.wav"
        if not img.exists():
            print(f"cena {n}: sem keyframe, pulando"); continue
        dur = dur_wav(wav) if wav.exists() else 4.0
        dur = max(1.5, dur + 0.15)
        out = cl / f"cena_{n:02d}.mp4"
        frames = int(dur * 30)
        # cover 720x1280 + zoom lento (ken burns)
        vf = (f"scale=900:1600:force_original_aspect_ratio=increase,crop=900:1600,"
              f"zoompan=z='min(zoom+0.0006,1.12)':d={frames}:x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':s=720x1280:fps=30,setsar=1")
        cmd = [FF,"-y","-loop","1","-i",str(img),"-t",f"{dur:.2f}","-vf",vf,
               "-c:v","libx264","-pix_fmt","yuv420p","-r","30","-an",str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"cena {n} ERRO ffmpeg:\n{r.stderr[-500:]}"); continue
        c["clipe"] = {"arquivo": f"cena_{n:02d}.mp4", "gerado": True,
                      "fal_request_id": None, "erro": None, "lipsync_aplicado": False}
        print(f"cena {n}: clipe imagem {dur:.1f}s ok")
    atomic_write_json(d / "roteiro.json", rot)
    print("montando mp4 final...")
    caminho = montagem_mod.montar(PRODUTO, vid, legendas=True)
    print("FINAL:", caminho)

if __name__ == "__main__":
    main()
