# Adendo — Entrevista (id: entrevista)

Você entrevista um especialista (ou cliente) sobre um tema ligado ao produto. O produto é a solução/resultado da conversa. Gravado como ABORDAGEM DE REPÓRTER NA RUA (repórter com microfone + entrevistado, os dois no MESMO quadro), tom credível de matéria de rua, não de estúdio. Prende no scroll porque parece um trecho de entrevista real, com autoridade e prova social.

## QUANDO USAR / PARA QUEM
Brilha quando o objetivo é AUTORIDADE e PROVA SOCIAL: persona cética, ticket mais alto, decisão racional. Ideal em consciência de solução, quando existe um especialista/caso que legitima o [mecanismo] e um número ou resultado concreto (da copy) que faz o convencimento. Tom mais sério e credível que depoimento ou esquete.

## ESTRUTURA / BEATS (NESTE FORMATO)
Trecho de entrevista de RUA em 4 a 6 cenas, ~3s cada, com os dois no quadro (two-shot), alternando quem fala. NESTE FORMATO a estrutura é:
1. PERGUNTA (fala o elenco B) — o repórter faz a pergunta que a persona faria sobre a [dor]/[nicho], microfone estendido pro entrevistado.
2. RESPOSTA COM AUTORIDADE (fala o elenco A) — o especialista/cliente responde encadeando o raciocínio ou o dado que sustenta o ponto.
3. PROVA/CASO (fala A, ou corte pontual pra `close_produto` físico) — cita caso, número ou resultado concreto da copy.
4. O PRODUTO ENTRA (fala A) — apresenta o [produto] como a solução/resultado natural daquela conversa.
5. (opcional) 2ª PERGUNTA (B) → aprofundamento (A) para reforçar.
6. CTA (fala A, vira pra câmera) — chama a ação e aponta o botão.

## LÓGICA DE COPY (o raciocínio replicável)
B fala pouco e pergunta com precisão; A conduz, explica e vende com tom seguro, frases de quem domina o assunto. A prova entra como resposta, não como propaganda. O [produto] aparece como conclusão da entrevista.
Moldes de pergunta (B): "E na prática, o que mais muda [resultado] pra quem sofre com [dor]?" / "Mas isso funciona mesmo pra quem [situação da persona]?"
Molde de resposta (A): "Olha, o que a gente vê é [mecanismo]. Um caso: [perfil] fez [ação] e chegou a [número/resultado]."
Fechamento (A, pra câmera): "Se você quer [resultado], clica no link aqui embaixo e [ação]."

## ASSINATURA VISUAL / KEYFRAMES
É uma ENTREVISTA DE RUA, tipo "abordagem de repórter na calçada", NÃO estúdio. O que faz parecer real: calçada/praça/feira/saída de academia ou shopping, PESSOAS PASSANDO desfocadas ao fundo, luz natural de dia, câmera na mão de quem grava (leve handheld). O repórter (B) segura um MICROFONE DE MÃO com espuma (cabeça de microfone tipo repórter) e o estende em direção a quem responde.
TWO-SHOT é a regra: no `prompt_keyframe`, descreva SEMPRE AS DUAS PESSOAS JUNTAS no mesmo quadro — o repórter (B) de um lado com o microfone, o entrevistado (A) do outro respondendo — em plano médio (cintura pra cima), 9:16. Descreva QUEM está falando nesta cena (boca levemente aberta, olhando pro outro) e QUEM está reagindo (ouvindo, acenando). As duas pessoas são DISTINTAS entre si (rosto, cabelo, roupa, idade, tom). Alterne o eixo/ângulo a cada cena (frontal do par, 3/4, plano um pouco mais fechado nos dois), mas o take padrão mantém os DOIS no frame. No CTA, o entrevistado (A) vira pra câmera.
ESCALA: pessoas e microfone em tamanho real; nada de objeto gigante. `prompt_movimento`: handheld de rua leve, o microfone passando sutil de um pra outro, gente andando ao fundo, gesto de mão ao explicar. Nunca zoom cinematográfico.

## TIPOS DE CENA / ELENCO
Two-shot de rua: o campo `elenco` indica QUEM FALA na cena — A = entrevistado (traz a autoridade/experiência) e B = repórter (faz as perguntas, segura o microfone). AS DUAS PESSOAS APARECEM NO MESMO KEYFRAME (este formato SOBREPÕE a regra-base de "nunca 2 pessoas no mesmo keyframe" — aqui o realismo EXIGE o par junto). Use `avatar_fala` com `elenco` "B" quando o repórter pergunta (A reage ao lado) e "A" quando o entrevistado responde (B ouve com o microfone estendido). Descreva SEMPRE os dois no `prompt_keyframe`; só um fala/lipsync por cena.
Para prova/produto, um corte pontual: FÍSICO — o entrevistado mostra o produto na mão (`close_produto`/`avatar_mostra`), em escala real. DIGITAL — o produto é só CITADO na fala; SEM tela/monitor na rua (no máximo o entrevistado ergue o próprio celular por 1 cena, em escala de mão).

## TEXTO NA TELA
A cara do formato inclui a legenda de fala (palavras aparecendo embaixo). A esteira NÃO queima esse texto no keyframe, então deixe todo o conteúdo na NARRAÇÃO; a legenda é adicionada depois. Não escreva o texto dentro da imagem.

## DO / DON'T
- DO: B pergunta o que a persona perguntaria; A responde com autoridade e experiência concreta da copy.
- DO: manter as DUAS pessoas no mesmo frame (repórter com microfone + entrevistado), na rua, gente passando ao fundo.
- DO: alternar QUEM FALA (elenco A/B) e o ângulo a cada cena; microfone de mão visível; mesma rua e luz.
- DON'T: nada de estúdio, bancada, mic de braço articulado ou pessoas sentadas — é abordagem de calçada.
- CONTINUIDADE (regra dura): cada fala EMENDA na anterior como conversa real — a resposta de A responde exatamente a pergunta de B; a próxima pergunta de B reage ao que A acabou de dizer. NADA de fala solta/órfã que não conecta (ex.: o repórter despejar um dado de mercado do nada). Quem tem a informação/autoridade é o entrevistado (A); o repórter (B) só pergunta e reage curto. Ao juntar os cortes em sequência, tem que soar um papo contínuo, não frases desconexas.
- DON'T: no digital, não colocar tela/monitor na rua; o produto é citado na fala.
- DON'T: inventar caso, número, preço ou resultado fora da copy; soar publicitário demais.
