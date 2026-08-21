# Adendo — Diálogo (id: dialogo)

Duas pessoas batendo papo natural: uma levanta a dúvida/objeção, a outra responde apresentando o produto. Prende no scroll porque o espectador se identifica com quem pergunta e recebe a resposta pronta, sem sensação de anúncio.

## QUANDO USAR / PARA QUEM
Brilha em consciência do problema/solução, quando há uma OBJEÇÃO forte a quebrar ("é caro", "é complicado", "é robótico", "não é pra mim"). O interlocutor B verbaliza exatamente a dúvida da persona; A responde com o [mecanismo] e o [resultado]. Ótimo pra topo e meio de funil: converte quem ainda desconfia.

## ESTRUTURA / BEATS (NESTE FORMATO)
Conversa pergunta-resposta em 4 a 6 cenas, ~3s cada. É um vaivém, não um monólogo:
1. GANCHO/OBSERVAÇÃO (elenco B) — B nota algo curioso na vida de A ("como seu [x] melhorou?", "que negócio é esse?").
2. REVELAÇÃO (elenco A) — A responde apontando o [produto]/[mecanismo] como a causa.
3. OBJEÇÃO (elenco B) — B levanta a dúvida real da persona ("mas isso não é [medo comum]?").
4. QUEBRA (elenco A) — A derruba a objeção com [prova/benefício] concreto da copy.
5. (opcional) 2ª OBJEÇÃO → QUEBRA — repete o vaivém se a copy tiver outra dúvida.
6. CTA (elenco B pergunta "como faço?" e/ou A fecha) — A aponta o botão embaixo.

## LÓGICA DE COPY (o raciocínio replicável)
Escreva como duas pessoas reais falando, frases curtas, uma reagindo à outra. B sempre pergunta/duvida; A sempre conduz e vende. Cada objeção de B é uma dor/medo verdadeiro; cada resposta de A entrega valor antes do CTA.
Moldes de gancho (elenco B): "Nossa, como seu [resultado] mudou? O que você fez?" / "Peraí, esse [produto] aí que você tá usando resolve [dor]?"
Molde de objeção (B): "Mas isso não é [medo: caro/difícil/demorado/robótico]?" → A: "Que nada, é [quebra concreta da copy]."
Fechamento (A): "Então corre, clica no botão aqui embaixo e [ação]."

## ASSINATURA VISUAL / KEYFRAMES
Cenário casual de dois amigos: canto de café do escritório, cadeiras no jardim, banco de shopping, sofá. Duas pessoas nitidamente DISTINTAS (roupas, cabelo e voz diferentes), com xícara/celular na mão, clima descontraído. No `prompt_keyframe`: sempre UMA pessoa por quadro (busto ou plano médio 3/4, olhando para o interlocutor fora do quadro ou reagindo), mesmo cenário/luz em todas as cenas, estética selfie caseira. Alterne enquadramento a cada corte. `prompt_movimento`: microcâmera handheld, leve gesto/riso, virar o rosto para "ouvir". Nunca ponha as duas pessoas no mesmo keyframe.

## TIPOS DE CENA / ELENCO
Base: `avatar_fala` com o campo `elenco` alternando: `"B"` nas cenas de pergunta/objeção, `"A"` (o avatar selecionado) nas cenas de resposta/venda. B é renderizado SEM as fotos do avatar (pessoa distinta). O diálogo é por CORTE ALTERNADO (shot-reverse): cada cena mostra só quem está no turno de fala. Intercale com `close_produto`/`avatar_usa` (físico) ou `tela_dispositivo` (digital) quando A demonstrar, para não empilhar duas falas idênticas.
NÃO usar o truque de gêmeos/mesma pessoa nos dois papéis: A e B são duas pessoas diferentes.

## TEXTO NA TELA
O formato não depende de texto queimado. A esteira não grava rótulo na imagem, então deixe a dúvida e a quebra na NARRAÇÃO. Se um selo curto for essencial, indique como legenda legível no `prompt_keyframe`, com moderação.

## DO / DON'T
- DO: B fala a objeção real da persona com as palavras dela; A responde entregando valor.
- DO: alternar elenco A/B a cada turno; uma pessoa por quadro; cenário e luz constantes.
- DON'T: duas pessoas no mesmo keyframe nem truque de gêmeos.
- DON'T: A monologando sem B reagir (vira depoimento, perde o charme do diálogo).
- DON'T: inventar prova, preço ou objeção que não estão na copy.
