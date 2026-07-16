---
name: gerar-prompts-imagem
description: A partir das copies aprovadas de um produto, gera o prompt de imagem de cada criativo (cena, ângulo, luz, ambientação) coerente com a copy e fiel ao produto real. Salva em prompts.json para a geração em lote. Use após aprovar as copies.
---

# Gerar Prompts de Imagem

Você transforma cada copy aprovada em um **prompt de imagem** para um criativo de anúncio.
Cada prompt descreve uma CENA (ângulo, iluminação, fundo, ambientação) coerente com a copy —
mas o produto deve permanecer **idêntico ao real**.

## Entrada
Qual produto (`products/<produto>/`). Se não estiver claro, pergunte.

## Passo a passo

1. **Leia:**
   - `products/<produto>/output/copies.md` — as copies aprovadas (por ângulo).
   - `products/<produto>/config.md` — regras visuais obrigatórias e proibições.
   - **Observe as imagens de `products/<produto>/referencia/`** (leia os arquivos) para entender
     exatamente como o produto é: formato, cores, tampa, rótulo, textos, proporções.

2. **Para cada copy**, crie 1 entrada de criativo com um `prompt` de imagem que:
   - Traduz a **mensagem/ângulo da copy** em uma cena visual (o que aparece, clima, contexto).
   - Define **ângulo de câmera, iluminação, fundo e ambientação** (é aqui que pode variar).
   - Respeita as **regras visuais** do `config.md` (cores da marca, estilo, o que sempre incluir)
     e as **proibições**.
   - **NÃO precisa repetir a regra de fidelidade** — a ferramenta injeta isso automaticamente. Mas
     descreva o produto de forma coerente com o real (não invente rótulos/cores/textos diferentes).
   - Seja concreto e visual. Evite texto sobreposto na imagem, a menos que a copy peça.

3. **Salve** em `products/<produto>/output/prompts.json` como uma lista JSON. Cada item:
   ```json
   {
     "id": "criativo_01",
     "angulo": "<nome do ângulo da copy>",
     "copy": "<a headline ou resumo curto da copy>",
     "tamanho": "1024x1024",
     "prompt": "<descrição visual da cena, ângulo, luz, fundo, ambientação>"
   }
   ```
   - `id` estável e sequencial (`criativo_01`, `criativo_02`, ...) — vira o nome do PNG.
   - Use `tamanho` do `config.md` (padrão `1024x1024`).

4. Confirme com o usuário e permita ajustes nos prompts antes de finalizar.

## Regras
- Uma cena por criativo, condizente com a copy correspondente.
- Fidelidade ao produto real é inegociável (a ferramenta reforça isso, mas não a contrarie no prompt).
- Ao final, avise: o próximo passo é abrir o painel (`python painel/app.py`) ou rodar
  `python gerar.py <produto>` para gerar as imagens em lote.
