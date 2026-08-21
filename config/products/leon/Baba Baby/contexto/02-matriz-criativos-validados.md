# Baba Baby — matriz de criativos apoiada em anúncios validados

Data da coleta: 2026-08-20

## Critério usado

- Anúncios ativos relacionados a celulite, flacidez, ação termogênica e redução de medidas.
- Longevidade como primeiro sinal: Peach Up desde 05/02/2026; Bumma desde 12/07/2026.
- Duplicação como segundo sinal: `collation_count` de até 4 versões para uma mesma peça.
- Convergência entre Peach Up e Bumma, marcas diferentes com a mesma estrutura de DR.
- Influenciadores conhecidos são marcados como evidência parcial, pois podem depender de audiência quente.
- Afiliados, institucionais e peças sem relação direta com o produto foram excluídos da modelagem.
- A Biblioteca não informa gasto ou ROAS. Longevidade e duplicação são proxies fortes, não prova financeira.

## Corpus coletado

- 51 anúncios estruturados.
- 100 mídias baixadas: 55 vídeos e 45 imagens.
- 19 imagens realmente únicas por hash no grupo estático analisado.
- 22 vídeos prioritários transcritos, contando variações de enquadramento; repetições de fala não foram tratadas como conceitos novos.
- Índice completo: `fontes-validadas/corpus/indice.json`.
- Mídias e transcrições: `fontes-validadas/corpus/midia/`.

## Achados que se repetem nos vencedores

### Copy de vídeo

1. Dor ou transformação no primeiro segundo, sem introdução.
2. Linguagem concreta e visual: “casca de laranja”, “perna flácida”, “barriga estufada”, “cintura afinada”.
3. Produto apresentado cedo e grande no quadro.
4. Demonstração da aplicação em movimento circular.
5. Sensação térmica usada como prova perceptível de mecanismo: esquenta, formiga, avermelha.
6. Prazo aparece depois do problema: primeiros sinais em 7/14 dias; resultado maior em 30 dias.
7. Prova visual em antes/depois, fita métrica ou comparação corporal.
8. CTA direto com oferta, desconto, kit ou link abaixo.

### Visual de vídeo

- Vertical 9:16, câmera de celular e ambiente doméstico.
- Corpo ou área-problema ocupa boa parte do primeiro quadro.
- Alternância curta entre rosto, área tratada, produto e aplicação.
- Legendas simples queimadas no vídeo.
- Pouca cenografia; aparência de conteúdo espontâneo.
- Variações duplicadas muitas vezes mudam apenas crop/proporção, preservando a mesma fala.
- Segundo formato comprovado: fundadora/especialista em talking head, produto empilhado à frente, pergunta ou palavra-chave grande na tela e antes/depois inserido.

### Estáticos

Os estáticos validados encontrados são de **DR padrão**, não WikiHow e não notícia. Os padrões recorrentes são:

- antes/depois + “resultado real”;
- corpo/área-problema + produto + benefícios;
- kit/preço/desconto + selos e CTA;
- headline grande, contraste alto, produto central e roxo/laranja como cor dominante.

Não há evidência suficiente neste corpus para colocar WikiHow ou notícia no primeiro teste.

## Peças-fonte prioritárias

### Peach Up

- `1440484601018034` — ativo desde 05/02, 4 versões. Prova visual + aplicação + resultado; DCO com duas proporções.
- `4455978804622990` — ativo desde 05/02, 2 versões. Hook “creme anticelulite viralizado”, casca de laranja → pele de pêssego, aplicação e calor.
- `1279422160747355` — ativo desde 05/02, 2 versões. Antes/depois corporal, produto cedo, tecnologia e prazo curto.
- `1611480816932260` — ativo desde 05/02, 2 versões. Oferta direta, problema nomeado e cupom.
- `1766988170937328` — objeção “não funciona?”, sequência de resultados reais, 7/30 dias e mecanismo.
- `2277718659427776` — pergunta “pode usar na barriga?”, resposta curta, mecanismo e CTA.
- `1865991594048315` — ativos nomeados, mecanismo e oferta.
- `968260319462801` — repetição visual antes/depois e prova desde a primeira aplicação.

### Bumma

- `1293286965987650` — ativo desde 12/07, 4 versões. Barriga, comparação com outros cremes, calor intenso, massagem e oferta.
- `1569638768506745` — ativo desde 12/07, 4 versões. Unboxing/reposição, redução de cintura, circulação, calor/formigamento e desconto.
- `1004632942558393` — 2 versões. Medida concreta, aplicação em barriga/coxa, termogênico visível e constância.
- `4430848743848140` — 2 versões. “Melhor investimento”, antes/depois, uso na barriga e coxa, demonstração completa.
- `1800796908015731` — fita métrica no primeiro quadro, contexto de hábitos e produto como auxílio.

### Evidência parcial ou excluída

- `913555754521269`: influenciadora conhecida; útil para estudar oferta e produto em quadro, mas não como principal prova de tráfego frio.
- `1041541392073590` e `1979039436816985`: programa de afiliados; excluídos por irrelevância.

## Recomendação de teste — paridade entre ofertas

Primeiro lote: **8 anúncios para cada página**, total de 16.

### Oferta 1 — Celulite

1. Vídeo UGC: casca de laranja → pele mais lisa; modela `4455978804622990`.
2. Vídeo UGC: perna flácida/celulite → transformação; modela `1279422160747355`.
3. Vídeo objeção/prova: “esse creme não funciona?” + sequência de resultados; modela `1766988170937328`.
4. Vídeo mecanismo/demonstração: aplicação, calor e circulação; modela `1440484601018034` + `4455978804622990`.
5. Vídeo especialista/talking head: ativos + explicação curta; modela `1865991594048315`.
6. Estático padrão: antes/depois + “resultado real, sem sorte”.
7. Estático padrão: área-problema + produto + três benefícios.
8. Estático padrão: kit/oferta/preço + selos + CTA.

### Oferta 2 — Barriga/redução de medidas

1. Vídeo UGC: fita métrica/medida no primeiro quadro; modela `1800796908015731`.
2. Vídeo UGC: “em duas semanas vou estar fina” + aplicação; modela `1293286965987650`.
3. Vídeo UGC: produto chegou/reposição + cintura; modela `1569638768506745`.
4. Vídeo pergunta e resposta: “pode usar na barriga?”; modela `2277718659427776`.
5. Vídeo demonstração: barriga, massagem circular, pele aquecendo; modela `1004632942558393` + `4430848743848140`.
6. Estático padrão: antes/depois de barriga + prazo.
7. Estático padrão: mecanismo termogênico + aplicação.
8. Estático padrão: kit/oferta/preço + CTA.

## Formatos do Criativos Express a usar

- `padrao` / UGC: formato principal, pois é o mais comprovado no corpus.
- `depoimento`: para antes/depois, objeção e transformação.
- `passo_a_passo`: somente para a demonstração de aplicação; mantém a estrutura validada de movimentos circulares + sensação térmica.
- `palestrinha`: para mecanismo/ativos com porta-voz, aproximando o talking head da fundadora.

Não usar no primeiro lote: podcast, entrevista de rua, experimento social, esquete, diálogo, POV cinematográfico, WikiHow ou notícia. Esses formatos existem na ferramenta, mas não apareceram como padrões vencedores no corpus analisado.

## Regra para as copies finais

Cada roteiro deverá registrar:

- ID do anúncio-fonte;
- trecho estrutural modelado;
- adaptação feita para Baba Baby;
- claim que possui suporte na oferta/página;
- visual por cena;
- o que foi deliberadamente removido.

Nenhuma promessa numérica de concorrente será transferida ao Baba Baby sem prova própria. Os números da IPclin e os claims presentes nas páginas são o limite factual da adaptação.
