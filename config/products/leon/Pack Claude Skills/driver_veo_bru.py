# -*- coding: utf-8 -*-
"""Anima os keyframes da Bru no Google Veo (omni, áudio nativo PT-BR) e junta por roteiro.
Motor único do projeto = Veo (Vertex AI, crédito Google). Idempotente: pula clipe já gerado.
"""
import sys, subprocess, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path.cwd()))
from backends import veo_backend as be
from app.pipeline import fala_veo

KF = Path("products/pack-claude-skills/output/ugc_bru")
OUT = KF / "clipes"; OUT.mkdir(parents=True, exist_ok=True)
FINAL = KF / "final"; FINAL.mkdir(parents=True, exist_ok=True)

VOZ = ("with a consistent, natural voice: a woman in her late 20s, warm, casual, medium pitch")
FFMPEG = "ffmpeg"

# (id, keyframe, fala PT-BR, duração alvo s) — pessoa sempre visível falando à câmera.
CENAS = {
 "r1": [
  ("r1_c1", "Gente, eu preciso te contar isso porque eu ainda tô meio em choque. Eu acabei de fechar um serviço de seiscentos reais, de uma coisa que eu não sei fazer.", 6),
  ("r1_c2", "Calma que eu explico. Existe uma skill do Claude, que é tipo um arquivinho que você arrasta lá dentro. Aí você dá um comando e ela faz o serviço inteiro por você.", 8),
  ("r1_c3", "Foi exatamente isso que eu fiz. Peguei um cliente, a skill montou tudo, eu só entreguei. Seiscentos reais. E tem gente cobrando de quinhentos a cinco mil por isso.", 8),
  ("r1_c4", "São doze skills que fazem isso por você, e não custa quase nada. Se você quer parar de perder essa onda, clica no botãozinho aqui embaixo.", 6),
 ],
 "r2": [
  ("r2_c1", "Eu passei meses achando que pra ganhar dinheiro com inteligência artificial eu precisava saber programar. Aí eu descobri que não precisa de nada disso. Zero.", 6),
  ("r2_c2", "Olha que ridículo de fácil: você baixa uma skill do Claude, arrasta o arquivo pra dentro, e pronto. Se você sabe arrastar um arquivo, você já sabe usar.", 8),
  ("r2_c3", "Eu fiz um app, fiz uma página de vendas, criei anúncio, tudo sem escrever uma linha de código. Coisa que designer e programador cobram os olhos da cara.", 8),
  ("r2_c4", "São doze skills prontas por dezessete reais, menos que um lanche. Clica aqui embaixo e vai testar. Você vai se assustar com o que dá pra fazer.", 6),
 ],
}


def _prompt_fala(dialogo: str) -> str:
    return (
        "The woman in the reference image looks straight at the camera and speaks in Brazilian "
        f"Portuguese, {VOZ}. No background music, no soundtrack, only her clean natural voice in a "
        "quiet room. She says exactly, with correct natural Brazilian pronunciation: "
        f'"{dialogo}". Handheld selfie video, home setting, lips perfectly synced to the speech. '
        "Authentic UGC, no on-screen text or captions.")


def gen(item):
    cid, fala, dur = item
    dest = OUT / (cid + ".mp4")
    if dest.exists() and dest.stat().st_size > 0:
        return f"PULADO {cid} (já existe)"
    kf = KF / (cid + ".png")
    if not (kf.exists() and kf.stat().st_size > 0):
        return f"FALHA {cid}: keyframe ausente"
    dialogo = fala_veo.adaptar(fala)
    t0 = time.time()
    try:
        be.generate(kf, _prompt_fala(dialogo), dest, duration_s=dur, resolution="720p",
                    model="veo_fast", gerar_audio=True, timeout=900)
        return f"OK {cid} ({round(time.time()-t0)}s)"
    except Exception as e:
        return f"FALHA {cid}: {str(e)[:220]}"


def concat(roteiro: str, cenas: list) -> str:
    clips = [OUT / (c[0] + ".mp4") for c in cenas]
    if not all(p.exists() and p.stat().st_size > 0 for p in clips):
        return f"CONCAT {roteiro}: pulado (faltam clipes)"
    lista = OUT / f"{roteiro}_list.txt"
    lista.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in clips), encoding="utf-8")
    dest = FINAL / f"ugc_bru_{roteiro}.mp4"
    r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-c:a", "aac", "-b:a", "128k", "-r", "30", str(dest)],
                       capture_output=True, text=True)
    return f"CONCAT {roteiro}: OK -> {dest.name}" if r.returncode == 0 else f"CONCAT {roteiro} FALHOU: {r.stderr[-300:]}"


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else "all"   # "r1" | "r2" | "all"
    roteiros = ["r1", "r2"] if alvo == "all" else [alvo]
    todos = [c for r in roteiros for c in CENAS[r]]
    print(f"Animando {len(todos)} cenas no Veo (roteiros: {roteiros})...", flush=True)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(gen, c): c[0] for c in todos}
        for f in as_completed(futs):
            print(f.result(), flush=True)
    for r in roteiros:
        print(concat(r, CENAS[r]), flush=True)
    print("=== FIM ===", flush=True)
