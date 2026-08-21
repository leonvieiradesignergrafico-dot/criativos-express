# -*- coding: utf-8 -*-
import sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path.cwd()))
from backends import codex_backend as be

prod = Path("products/pack-claude-skills")
out = prod/"output"/"criativos_lote2"; out.mkdir(parents=True, exist_ok=True)
ANEX = "Nao ha imagens anexadas; gere a imagem inteiramente a partir do briefing de texto abaixo."

# Reforco explicito: renderizar TODOS os acentos do portugues corretamente.
ACENTO = ("ATENCAO A ORTOGRAFIA: escreva TODO o texto em portugues do Brasil com os "
          "ACENTOS corretos exatamente como grafados abaixo (til, agudo, circunflexo, cedilha). "
          "Nao remova acentos. ")

itens = [
  {
    "id": "lote2_02",
    "prompt": ACENTO + "Anuncio QUADRADO 1:1, design limpo e premium, fundo escuro quente com leve textura tech, destaque terracota (#CC785C). Comparacao visual lado a lado em dois cards: card da esquerda apagado/cinza com um X vermelho discreto e o rotulo 'IA comum: so responde'; card da direita em destaque terracota com um check e o rotulo 'Skill do Claude: faz o servico inteiro'. NAO usar logotipos reais de nenhuma marca (apenas texto neutro 'IA comum'). COMPOSICAO SEGURA: tudo no centro com margem (nada nas bordas). Textos EXATOS com acentuacao correta: headline bold branca no topo, duas linhas, com 'por voce' em terracota -> 'A IA comum so conversa.' e 'Essa faz o servico por voce' (grafar: 'so' como SO com acento -> so=“só”; 'servico' -> 'serviço'; 'voce' -> 'você'). Selo: 'as 12 skills por R$17'. Botao terracota: 'Quero a que faz'. Hierarquia clara, texto nitido. Anuncio de resposta direta profissional."
  },
  {
    "id": "lote2_05",
    "prompt": ACENTO + "Anuncio QUADRADO 1:1, design minimalista premium, fundo escuro quente com gradiente sutil e leve textura, muito espaco negativo, destaque laranja terracota. Tipografia grande como protagonista, sem foto de pessoa. Tres blocos numericos grandes empilhados e alinhados ao centro: '12 servicos', '1 comando', 'R$17' (o 'R$17' em terracota, o maior). Um pequeno icone de cursor/seta terracota como detalhe. COMPOSICAO SEGURA: todo o texto no centro com margem folgada (nada nas bordas). Textos EXATOS com acentuacao correta do portugues: grafar 'servicos' como 'serviços' e 'voce' como 'você'. Apoio pequeno abaixo em cinza claro: 'skills do Claude que fazem o trabalho por voce' (com 'você' acentuado). Botao terracota: 'Quero as 12 skills'. Texto nitido, hierarquia forte. NAO inventar logotipo. Anuncio de resposta direta de alto nivel."
  },
]

def gen(p):
    dest = out/(p["id"]+".png")
    t0=time.time()
    try:
        be.generate(p["prompt"], [], dest, size="1024x1024", timeout=600,
                    reasoning="low", anexos_desc=ANEX)
        return f"OK {p['id']} ({round(time.time()-t0)}s)"
    except Exception as e:
        return f"FALHA {p['id']}: {str(e)[:200]}"

with ThreadPoolExecutor(max_workers=2) as ex:
    futs=[ex.submit(gen,p) for p in itens]
    for f in as_completed(futs):
        print(f.result(), flush=True)
print("=== FIM ===", flush=True)
