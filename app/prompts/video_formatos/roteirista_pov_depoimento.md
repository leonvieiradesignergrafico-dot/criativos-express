# Adendo — POV + Depoimento

Formato COMBINADO: abre num POV imersivo (o espectador SENTE a dor por dentro) e CORTA para um depoimento de cliente real que valida essa mesma dor e mostra a solução. Para o scroll porque prende pela vivência antes de provar pela prova social.

## QUANDO USAR / PARA QUEM
Brilha em consciência baixa a média que ainda precisa se reconhecer na dor ANTES de aceitar a prova. O POV faz o espectador dizer "sou eu"; o depoimento entrega quem já saiu disso com [produto]. Ideal pra [nicho] onde a dor é emocional/cotidiana e a objeção é "será que funciona pra mim". Só use com depoimento real (ou avatar autorizado a encarnar o cliente); nunca invente história.

## ESTRUTURA / BEATS (curto)
NESTE FORMATO a estrutura tem DUAS PARTES coladas por um CORTE SECO. Em 4 a 6 cenas:
1. **POV DA DOR** (2-4s) — a situação incômoda vivida em 1ª pessoa, câmera subjetiva, legenda "POV: você [dor/situação]".
2. **POV RECONHECIMENTO** (2-3s, opcional) — o "você" nomeia o que sente, ainda dentro da cena.
   >>> CORTE SECO: aqui a peça VIRA. Sai da câmera subjetiva e revela-se o rosto de quem vivia o POV — É A MESMA PESSOA (mesmo avatar/fotos anexadas), agora de frente pra câmera; no POV o rosto não aparecia por ser câmera subjetiva. NÃO introduza uma segunda pessoa nem um rosto novo. Marque a transição só pelo enquadramento (subjetiva → rosto do mesmo avatar em selfie honesta).
3. **DEPOIMENTO / ANTES** (2-3s) — cliente valida a MESMA dor do POV ("eu vivia exatamente isso").
4. **DEPOIMENTO / MUDANÇA** (3-4s) — como encontrou o [produto] e o clique de virada.
5. **DEPOIMENTO / RESULTADO+PROVA** (3-4s) — resultado concreto com demonstração real (antes/depois, produto em uso, tela).
6. **CTA** (2-3s) — o cliente convida pro [resultado].
Copy curta comprime pra 4 cenas: POV dor → depoimento antes → resultado+prova → CTA. Nunca alongue à toa.

## LÓGICA DE COPY
A ponte é a DOR ÚNICA: o que o POV faz o espectador SENTIR é exatamente o que o depoimento CONFIRMA ter vivido. A parte POV começa DENTRO da experiência (fala em "você/eu", legenda carrega o gancho); depois do corte, muda pro relato de gente real, coloquial, no tempo verbal antes→agora.
Moldes de gancho:
- POV: "POV: você [situação cotidiana] e percebe que [dor/verdade incômoda]."
- Ponte pro depoimento: "Eu vivia exatamente isso, até que [descoberta do produto] e [resultado]."
O produto entra no depoimento como o que MUDOU o jogo, nunca como pitch cortado. Fecha com o cliente chamando pro botão.

## ASSINATURA VISUAL / KEYFRAMES
Duas estéticas coladas. POV: `prompt_keyframe` com enquadramento de 1ª pessoa, câmera na linha dos olhos como quem segura o celular, cenário caseiro coerente com [nicho], perspectiva subjetiva do que a pessoa vê; legenda "POV: você..." sobreposta legível só na abertura. Depoimento: selfie honesta, cliente segurando o celular, rosto grande, olhar direto, luz natural do cômodo, plano variando (close → médio → prova real). Deixe o CORTE visível pela mudança de câmera (subjetiva → rosto na câmera). `prompt_movimento`: no POV, micro mão no celular, respiração, leve pan como olhar; no depoimento, micro handheld, aceno leve, virar o antes/depois devagar. Sempre sutil.

## TIPOS DE CENA / ELENCO
POV (físico): avatar_usa, close_produto MOSTRANDO A DOR (o problema em 1ª pessoa), nunca o produto-solução ainda. POV (digital): o produto NÃO aparece no POV — mostre o CONTEXTO da dor (a tela bagunçada/o problema que a pessoa vive), não a interface do produto; o produto digital é só CITADO/revelado depois do corte. Depoimento: avatar_fala pro cliente, alternado com avatar_usa/close_produto (físico) ou, no digital, no MÁXIMO 1 cena de tela_dispositivo/mockup_resultado com o dispositivo a distância natural (na mão do cliente), nunca tela gigante ou na cara. Uma pessoa só, em 1ª pessoa (o "você" do POV vira o mesmo cliente que depõe): sem segunda pessoa, sem elenco B, omita o campo `elenco`. O CTA é dito pelo próprio cliente.

## TEXTO NA TELA
A legenda "POV: você..." é a cara da abertura: coloque como legenda/indicação sobreposta no `prompt_keyframe` só na 1ª cena e repita a essência na narração. A identidade do depoente vai na NARRAÇÃO da 1ª cena de depoimento ("aqui é a [nome], sou cliente há [tempo]"), não em letreiro. Rótulos ANTES/DEPOIS só no keyframe quando a foto comparativa real existe. A esteira não queima texto na imagem.

## DO / DON'T
- DO: abrir em POV subjetivo e deixar o CORTE SECO pro depoimento nítido (muda a câmera).
- DO: amarrar a MESMA dor nas duas partes; o depoimento confirma o que o POV fez sentir.
- DO: manter o depoimento como gente real (hesitação, coloquial) e a prova algo que existe.
- DON'T: descrever a cena de fora no POV; fale em "você/eu".
- DON'T: começar pelo produto nem misturar as duas estéticas na mesma cena; a virada tem que ser clara.
