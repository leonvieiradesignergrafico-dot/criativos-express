# -*- coding: utf-8 -*-
"""Keyframes UGC do avatar Bru (2 roteiros x 4 cenas). Usa as 3 refs da Bru p/ consistencia."""
import sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path.cwd()))
from backends import codex_backend as be

BRU = Path("avatares/Bru/referencia")
REFS = [str(BRU/"ref_01_busto.png"), str(BRU/"ref_02_corpo.png"), str(BRU/"ref_03_perfil.png")]
out = Path("products/pack-claude-skills/output/ugc_bru"); out.mkdir(parents=True, exist_ok=True)

ANEX = ("Sao 3 fotos de referencia do AVATAR (a mesma mulher): mantenha rosto, cabelo, tom de pele e "
        "identidade IDENTICOS aos das fotos em todas as cenas. Recrie a pessoa na cena nova, nao cole a foto.")

BASE = ("Enquadramento VERTICAL 9:16, estetica UGC caseiro real (foto/selfie de celular, leve grao, "
        "luz natural de janela, ambiente domestico simples com parede clara ao fundo). A mulher veste "
        "camiseta PRETA lisa basica, SEM estampa/logo. Sem nenhum texto ou legenda sobreposta na imagem. "
        "Nada de estudio. ")

cenas = [
  # Roteiro 1
  ("r1_c1", BASE+"Close frontal do rosto e busto, ela segura o celular esticado pra selfie, olhando direto pra camera, "
   "expressao de surpresa feliz/empolgada como quem vai contar uma novidade boa. Boca levemente aberta falando."),
  ("r1_c2", BASE+"Ela sentada de lado a uma mesa, do peito pra cima, virada para a tela de um notebook a frente, mao apontando "
   "para a tela. Na tela, interface de chat de IA GENERICA em modo escuro (sem marca/logo, texto desfocado). Expressao explicando algo."),
  ("r1_c3", BASE+"De volta ao rosto em close selfie, sorriso confiante e orgulhoso, como quem acabou de contar que ganhou dinheiro. "
   "Olhando pra camera, gesticulando de leve com a mao."),
  ("r1_c4", BASE+"Close selfie frontal, expressao animada e direta (convite/CTA), sobrancelha levantada como quem incentiva, "
   "levemente inclinada pra frente em direcao a camera."),
  # Roteiro 2
  ("r2_c1", BASE+"Close selfie frontal, expressao de alivio e leve riso, como quem admite que estava errada. Olhando pra camera falando."),
  ("r2_c2", BASE+"Angulo mostrando a mao dela arrastando um icone de arquivo para dentro de um notebook com interface de IA GENERICA "
   "(sem marca, area de soltar arquivo), ela aparecendo parcialmente ao lado sorrindo, ambiente caseiro."),
  ("r2_c3", BASE+"Ela do peito pra cima apontando para a tela do notebook com entusiasmo, mostrando um app/pagina pronta na tela "
   "(interface generica sem marca). Expressao empolgada."),
  ("r2_c4", BASE+"Close selfie frontal, expressao simpatica de convite, sorriso natural, gesticulando pra baixo como quem indica "
   "o botao abaixo. Olhando direto pra camera."),
]

def gen(item):
    cid, prompt = item
    dest = out/(cid+".png")
    # Idempotente: pula keyframe que já existe com conteúdo (não regera os bons nem gasta quota).
    if dest.exists() and dest.stat().st_size > 0:
        return f"PULADO {cid} (já existe, {dest.stat().st_size} bytes)"
    t0=time.time()
    try:
        be.generate(prompt, REFS, dest, size="1024x1536", timeout=600, reasoning="low", anexos_desc=ANEX)
        return f"OK {cid} ({round(time.time()-t0)}s)"
    except Exception as e:
        return f"FALHA {cid}: {str(e)[:200]}"

with ThreadPoolExecutor(max_workers=3) as ex:
    futs=[ex.submit(gen,c) for c in cenas]
    for f in as_completed(futs):
        print(f.result(), flush=True)
print("=== FIM ===", flush=True)
