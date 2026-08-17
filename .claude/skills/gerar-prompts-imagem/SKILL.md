---
name: gerar-prompts-imagem
description: A partir das copies aprovadas de um produto, gera o prompt de imagem de cada criativo (cena, ângulo, luz, ambientação) coerente com a copy e fiel ao produto real. Salva em prompts.json para a geração em lote. Use após aprovar as copies.
---

# Gerar Prompts de Imagem

Você transforma cada copy aprovada em um **prompt de criativo completo** (cena + copy
diagramada na arte). Cada prompt encena o ângulo da copy numa CENA escolhida de propósito —
mas o produto deve permanecer **idêntico ao real**.

> **Cérebro obrigatório:** antes de tudo, leia `app/prompts/diretor_arte.md` — é o framework
> de direção de arte/prompt engineering (taxonomia de tipos de criativo, modo realista vs.
> cinematográfico, regras anti-logo, tipografia e CTA, anatomia do prompt). Compartilhado
> com o app; siga-o. Este SKILL cuida só do fluxo de arquivos abaixo.

## CRITÉRIO VISUAL DE ALTA PERFORMANCE (a imagem tem que PARAR o scroll e TANGIBILIZAR o gancho)

A imagem tem UM trabalho: interromper o dedo no feed e tornar VISÍVEL o gancho/promessa da copy.
Nada genérico, decorativo ou "bonito e morno". A régua de mercado (Meta 2025 + benchmarks de
static ads): **alto contraste de luminância entre o assunto e o fundo** é o que cria o "pop" que
para o scroll; **um único ponto focal** (uma coisa pra olhar); **rosto/emoção humana** puxa
atenção mais que produto solto; **pouco texto e legível no mudo** (a maioria vê sem som e no
celular). Cada prompt PRECISA cumprir:

1. **TANGIBILIZA O GANCHO, não decora.** A cena tem que ENCENAR o ângulo da copy (dor, desejo,
   pertencimento, mecanismo, prova, ocasião), não pousar o produto ao lado de um prop. Se a copy
   é de dor, mostre o estado/alívio; se é pertencimento, mostre a identidade; se é presente,
   mostre a entrega real. Cena que "só existe ao lado do produto" = reprovada.
2. **THUMB-STOP VISUAL:** alto contraste, luz dramática de campanha (cinematográfico é o padrão),
   cor de destaque com atitude usada UMA vez só, composição forte. Fundo preto liso de estúdio e
   produto flutuando = a própria foto de referência = reprovado. Ambientação com CLIMA é o padrão.
3. **UM PONTO FOCAL + ROSTO/EMOÇÃO quando o ângulo pedir.** Uma coisa domina o quadro. Rosto
   humano com emoção real (não modelo de banco de imagem) quando o ângulo é dor/desejo/prova/
   pertencimento, com roupa lisa neutra (regra anti-logo do cérebro).
4. **LEGIBILIDADE MOBILE / NO MUDO:** o texto da arte tem que ser lido em 2s num celular. Reserve
   um LADO LIMPO / zona de respiro (um lado mais escuro ou de baixa informação) pra headline +
   apoio + botão caberem legíveis. Tipografia pesada e com textura/alma (nunca fonte fina que
   some, nunca "sans-serif bold" genérica). Texto ocupa pouca área da tela; nada de parede de texto.
5. **MESSAGE MATCH:** o visual conta a MESMA história da copy e da página. Visual e headline nunca
   se contradizem. Em 1 frame dá pra saber a categoria do produto.
6. **VARIAÇÃO REAL NO LOTE:** cada criativo muda ângulo de câmera + ambientação + luz. Dois com o
   mesmo pose/fundo = lote reprovado. Fidelidade ao PRODUTO real é inegociável; o resto da cena é livre.

### AUDITORIA VISUAL OBRIGATÓRIA antes de finalizar o prompts.json (gate)
Antes de fechar cada entrada, pontue o prompt de 0 a 3 em cada eixo e **reescreva no ato** o que
ficar fraco (nada < 2 passa):
- **THUMB-STOP (0-3):** contraste + ponto focal + luz de campanha param o scroll? (0-1 = still de estúdio genérico → refaça a cena)
- **TANGIBILIZA O GANCHO (0-3):** a cena encena o ângulo da copy, ou é produto decorado no vácuo?
- **LEGIBILIDADE MOBILE (0-3):** tem zona limpa pro texto, tipografia com alma, lê em 2s no mudo?
- **MESSAGE MATCH + FIDELIDADE (0-3):** conta a história da copy e o produto está idêntico à referência?
- **VARIAÇÃO (0-3):** ângulo/ambientação/luz diferentes da referência E dos outros do lote?
Ao mostrar o plano do lote (passo 5), inclua uma coluna de checagem confirmando que nenhum
criativo ficou < 2 em qualquer eixo (regenere antes de finalizar os que ficarem).

## Execução enxuta (leia uma vez, siga direto)
- **Leia UMA vez** o cérebro (`app/prompts/diretor_arte.md`) e, no passo 1, o `copies.md`, o
  `config.md` e as imagens de `referencia/`. **Não releia** o cérebro nem este SKILL por criativo.
- **Leia SÓ a pasta do produto.** Não varra o repositório.
- 1 entrada de prompt por copy aprovada; pare quando o `prompts.json` estiver completo e confirmado (passo 5).

## Entrada
Qual produto (`products/<produto>/`). Se não estiver claro, pergunte.

## Passo a passo

1. **Leia:**
   - `products/<produto>/output/copies.md` (e `copies.json`, se existir) — as copies
     aprovadas, com `headline`, `subheadline` (opcional), `apoio` (parágrafo de apoio de
     2-3 linhas, opcional) e `cta` por ângulo.
   - `products/<produto>/config.md` — regras visuais obrigatórias e proibições.
   - **Observe as imagens de `products/<produto>/referencia/`** (leia os arquivos) para
     entender exatamente como o produto é: formato, cores, tampa, rótulo, textos, proporções.

2. **Planeje o lote antes de escrever** (a etapa que separa lote bom de lote genérico):
   - Para cada copy, escolha conscientemente o **tipo de criativo** da taxonomia do cérebro
     (hero de estúdio, produto em uso, lifestyle na mão, cena de presente, flat-lay, UGC,
     unboxing, oferta gráfica, detalhe macro) e o **modo** (realista orgânico ou
     cinematográfico), conforme o ângulo da copy.
   - **Decida a AMBIENTAÇÃO de cada criativo, não só o formato.** Referência boa nunca é
     produto no vácuo preto — é produto dentro de um clima (arquibancada desfocada, refletor
     de estádio, gramado molhado, punho erguido na torcida, respingo/grunge, cena de presente
     em casa). Fundo preto liso de estúdio é PROIBIDO como padrão.
   - **Anti-replicação da foto de referência (regra dura do cérebro):** a foto de referência
     serve para copiar o PRODUTO, não a cena. Cada criativo tem que usar um ÂNGULO diferente
     do da foto de referência e diferente dos outros criativos do lote. Antes de escrever,
     anote o que muda neste criativo (ângulo + ambientação + luz). Produto flutuando em três
     quartos sobre fundo preto = a própria foto de referência = reprovado.
   - **Varie no lote**: nunca entregue tudo em still de estúdio; misture formatos, modos e
     ambientações. Dois criativos com o mesmo pose/fundo = lote reprovado.
   - **Conflito config × copy:** se uma proibição do config impedir o formato ideal (ex.:
     config proíbe pessoas, mas a copy é de presente e pede cena de entrega), PARE e avise
     o usuário — proponha ajustar o config ou trocar o formato. Não degrade em silêncio.

3. **Para cada copy**, crie 1 entrada de criativo cujo `prompt` é **CURTO e NATURAL — 60 a 110
   palavras**, no estilo de quem dirige um designer (ver o EXEMPLO no topo do `diretor_arte.md`).
   Prompt longo e mandão sufoca o modelo e cai no still estéril — é o erro que estamos
   corrigindo. Densidade de decisão, não volume de adjetivo. NÃO microgerencie câmera, lente,
   f-stop, cada sombra — dê a vibe e as restrições e deixe o modelo desenhar. O prompt:
   - Diz o que é o anúncio e a **cena/vibe** em linguagem de gente, com **layout espacial
     simples** (onde vai o texto, onde vai o produto). Ângulo diferente da foto de referência;
     ambientação com clima (não fundo preto vazio por padrão).
   - Diz **produto idêntico à referência mas REDESENHADO na cena, não colado/recortado**.
   - **Tipografia com alma** em uma frase de vibe (lettering pincelado / grotesca pesada com
     textura esportiva no clima de torcida), nunca só 'sans-serif bold' genérica.
   - **Cor de destaque uma vez só:** a cor viva da marca (ex.: vermelho) aparece em UM único
     elemento (tarja/selo OU botão, nunca os dois). Respeite a regra do config.
   - **Anti-logo:** nunca peça logos, escudos, emblemas ou estampas que não estejam no
     produto de referência; pessoas em cena vestem roupas lisas neutras (escreva isso no
     prompt quando houver pessoa).
   - Inclui a **camada gráfica** com os textos LITERAIS da copy entre aspas simples:
     headline, subheadline OU apoio (só se existir; apoio = parágrafo de 2-3 linhas
     diagramado como as referências), CTA como botão clicável COMPACTO (pílula
     contida, na cor de destaque, jamais pill gigante branco), e selo só se você definir o
     campo `selo`. Nunca invente texto extra.
   - **ACENTO É OBRIGATÓRIO E LITERAL (regra dura):** copie o texto da copy com TODOS os
     acentos e a cedilha EXATAMENTE como no `copies.md` — `á â ã à ç é ê í ó ô õ ú`. É
     PROIBIDO transliterar para ASCII / "sem acento" (nunca escreva `Nao`, `voce`, `alianca`,
     `Ja`, `explicacao` — escreva `Não`, `você`, `aliança`, `Já`, `explicação`). O modelo de
     imagem desenha exatamente o que estiver escrito aqui; se você tirar o acento, a arte sai
     errada. Vale para headline, apoio, selo e CTA, em TODOS os criativos.
   - Respeita as **regras visuais** e **proibições** do `config.md`.
   - **NÃO precisa repetir a regra de fidelidade** — a ferramenta injeta isso
     automaticamente. Mas descreva o produto de forma coerente com o real.

4. **Salve** em `products/<produto>/output/prompts.json` como uma lista JSON. Cada item:
   ```json
   {
     "id": "criativo_01",
     "angulo": "<nome do ângulo da copy>",
     "copy": "<a headline ou resumo curto da copy>",
     "formato": "<tipo da taxonomia, ex. cena_presente>",
     "estilo": "<realista | cinematografico>",
     "selo": "<texto curto do badge ou string vazia>",
     "tamanho": "1024x1024",
     "prompt": "<direção de arte completa: cena + diagramação, conforme o cérebro>"
   }
   ```
   - `id` estável e sequencial (`criativo_01`, `criativo_02`, ...) — vira o nome do PNG.
   - Se a copy tiver `id`/`copy_id`, inclua `copy_id` para rastreio.
   - Use `tamanho` do `config.md` (padrão `1024x1024`).
   - A geração (`gerar.py`) usa só `id`, `tamanho` e `prompt` — `formato`, `estilo` e
     `selo` documentam a decisão, mas ela precisa estar escrita DENTRO do `prompt`.
   - Dentro dos valores, só aspas simples; nunca hífen nem travessão em texto da arte.
   - **Preserve os acentos do português em TODO texto da arte** (headline, apoio, selo, CTA):
     `Não`, `você`, `aliança`, `explicação` — NUNCA em ASCII (`Nao`, `voce`). Transliterar é erro.

5. **Confirme com o usuário** mostrando o plano do lote (tabela: id, ângulo, formato,
   estilo) e permita ajustes nos prompts antes de finalizar.

## Regras
- Uma cena por criativo, encenando a copy correspondente — cena de presente tem que ter
  cara de presente de verdade (entrega, caixa aberta, gesto), não produto ao lado de um laço.
- **Nunca replicar o ângulo/fundo da foto de referência** — cada criativo muda ângulo +
  ambientação + luz. Produto flutuando em três quartos no fundo preto = reprovado.
- **Ambientação emocional é o padrão, fundo preto vazio não.** Traga clima de torcida/uso/
  presente para o fundo, mantendo um lado limpo para o texto.
- Fidelidade ao produto real é inegociável (a ferramenta reforça isso, mas não a contrarie
  no prompt). Todo o resto da cena é livre.
- Cor de destaque da marca usada uma vez só (tarja OU botão); botão de CTA compacto, nunca
  pill gigante branco.
- Proibido inventar logos, escudos, emblemas e estampas de marca — em selos, roupas, props.
- Ao final, avise: o próximo passo é abrir o painel (`python painel/app.py`) ou rodar
  `python gerar.py <produto>` para gerar as imagens em lote.
