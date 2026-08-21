# Adendo — Experimento Social

Um teste ao vivo na rua, com público real, que prova o valor de [produto] de um jeito inegável. A câmera flagra a reação genuína de alguém comum e o espectador sente que aquilo é verdade, não propaganda.

## QUANDO USAR / PARA QUEM
Público em consciência baixa a média, cético, que já viu promessa demais. Brilha quando dá pra DEMONSTRAR [mecanismo] ou [resultado] na prática diante de um estranho. Objetivo: quebrar descrença gerando curiosidade e prova social ao vivo.

## ESTRUTURA / BEATS (curto)
NESTE FORMATO a estrutura é experimento em 3 atos:
1. **Montagem do teste (cena 1, 2 a 3s)** entrevistador com microfone aborda alguém na rua e lança a pergunta/desafio que arma o experimento.
2. **Execução (cenas 2 a 3, 3 a 4s)** a pessoa responde, testa ou reage; o entrevistador provoca ("e se eu te dissesse que...") e revela [produto]/[mecanismo].
3. **Reação e resultado (cena 4, 3 a 4s)** o espanto genuíno da pessoa vira a prova; entrevistador fecha com CTA direto ao público.

## LÓGICA DE COPY (o raciocínio replicável)
Diálogo curto, pergunta e resposta, tom de flagrante espontâneo. Gancho sempre é uma pergunta que expõe uma crença comum.
- Molde A: "Você acha que [crença limitante sobre nicho]? Deixa eu te mostrar uma coisa..."
- Molde B: "Se eu te falar que dá pra [resultado] sem [dor comum], você acredita?"
Encadeia com o entrevistado duvidando e cedendo aos poucos; [produto] entra como a explicação do que ele acabou de ver. CTA na boca do entrevistador, apontando pro link: "quem quiser testar, tá no link aqui embaixo".

## ASSINATURA VISUAL / KEYFRAMES
Rua, calçada, avenida movimentada ou praça (cenário público reconhecível ao fundo, pessoas passando desfocadas). Prop-chave: microfone de mão do entrevistador. Luz natural de dia, câmera na mão, vertical caseiro. O enquadramento PADRÃO é TWO-SHOT — entrevistador e entrevistado JUNTOS no mesmo quadro, o microfone estendido em direção a quem responde. `prompt_keyframe`: descreva SEMPRE as DUAS pessoas juntas (distintas entre si), marcando quem FALA (boca aberta, olhando pro outro) e quem REAGE (surpresa, riso, dúvida), fundo urbano real com gente passando desfocada. Só uma fala/lipsync por cena. Pode intercalar 1 ou 2 closes de reação de uma pessoa só pro ritmo, mas a abordagem e a reação-clímax são two-shot. ESCALA: pessoas e microfone em tamanho real, nada gigante. `prompt_movimento`: leve tremor de câmera de mão, pessoas ao fundo se movendo, o microfone passando de um pra outro.

## TIPOS DE CENA / ELENCO
As DUAS pessoas são GERADAS para este take (dupla de rua) — NÃO use o avatar de casa nem as fotos de referência do avatar para nenhuma delas; não inicie o `prompt_keyframe` com "A pessoa das fotos de referência do avatar". Descreva entrevistador e entrevistado como pessoas novas e distintas. MESMA rua/esquina, MESMA luz e MESMAS duas pessoas em TODAS as cenas — só muda o ângulo/enquadramento e quem fala; nunca troque de quarteirão nem de dupla entre cortes. É entrevista/abordagem de rua: `elenco` A (entrevistador, segura o microfone) e B (entrevistado). Este formato SOBREPÕE a regra-base de "nunca 2 pessoas no mesmo keyframe": o padrão é TWO-SHOT (as duas juntas no quadro), porque é o realismo da abordagem na rua; o `elenco` marca QUEM FALA na cena (só essa pessoa tem lipsync). Tipos: `avatar_fala` (two-shot, um falando) alternado com close de reação e com `avatar_mostra`/`close_produto` quando o [produto] FÍSICO for revelado. DIGITAL: o produto é CITADO/revelado na fala, não mostrado em tela; no máximo o entrevistador ergue o próprio celular por 1 cena, escala de mão — nunca tela grande ou b-roll de interface no meio da rua.

## TEXTO NA TELA
O formato vive de legenda grande palavra a palavra (estilo caption viral). A esteira não queima texto no keyframe; embuta a fala inteira na `narracao` (as legendas saem dela). Só indique um rótulo no keyframe se for essencial e legível.

## DO / DON'T
- DO: cenário de rua real e microfone visíveis; reação genuína como clímax.
- DO: pergunta-gancho que expõe uma crença antes de revelar [produto].
- DON'T: NÃO fabrique prova. O teste tem que ser algo executável de verdade na esteira; nada de resultado ou reação inventada que não dê pra filmar honestamente.
- DON'T: cenário de estúdio (é rua). O two-shot com as duas pessoas juntas é o padrão na abordagem e na reação-clímax — não caia no corte alternado da regra base.
- DON'T: CTA sem antes ter entregue a reação que serve de prova.
