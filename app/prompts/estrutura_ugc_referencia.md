# Manual da estrutura UGC (extraído de 10 anúncios reais do usuário)

Destilado de 10 UGCs de tráfego pago (Body Splash e Pulseira do Corinthians), cruzando
frames + legendas + transcrição de áudio. É a ESTRUTURA (esqueleto reutilizável), não a copy —
a copy é sempre nova; o que se repete é a arquitetura abaixo.

## Formato base (invariante)
- Vertical 9:16, 10-17s (miolo ~12-14s), uma pessoa, um cômodo de casa, selfie na mão, luz natural.
- Voz da própria pessoa dirige tudo (não é vídeo com trilha muda — é fala + legenda).
- Legenda rolando embaixo acompanhando a fala SEMPRE. Gancho fixo no topo é opcional (ex.: "Você não vai acreditar no que ela disse 😱").
- Produto quase sempre erguido perto do rosto (enquadramento herói). Pelo menos 1 close do produto (no corpo, no rótulo, na mão).
- 1 beat de DEMONSTRAÇÃO: borrifar no corpo (spray) / vestir + close no pulso (vestível) / abrir-usar.
- Energia por JUMP CUT: a mesma pessoa/enquadramento cortada em vários takes curtos (2 a 8 cortes por vídeo), microvariações de ângulo/expressão. Cada beat pode virar 1-2 takes.

## O esqueleto de 5 beats (a ORDEM é fixa; beats podem fundir/sumir em vídeos curtos, nunca reordenar)

1. **GANCHO (0-3s, 1ª fala)** — prende em 3s. Sabores observados:
   - Curiosidade: "eu tava só esperando essa oportunidade" / "você não vai acreditar"
   - Anúncio/novidade: "o Corinthians lançou seu body splash oficial" / "chegou a pulseira oficial"
   - Choque de preço: "paguei só 1 real nessa pulseira" / "vi por apenas 1 real"
2. **REAÇÃO / PROVA (miolo)** — prova social em 1ª pessoa: "eu já garanti o meu" / "a minha chegou hoje, super rápido" / "quando senti o cheiro me surpreendi" / "o material me surpreendeu". Costuma vir COM a demonstração.
3. **BENEFÍCIO** — sensorial/funcional concreto: "o cheiro é muito gostoso" / "passa de manhã e fica o dia inteiro" / "ficou linda no braço, vale muito mais do que paguei".
4. **OFERTA + ESCASSEZ (quase sempre fundidos)** — preço/condição ("por só R$97" / "pagando só o frete") + urgência ("últimas unidades" / "último lote" / "só tem mais 700" / "quase esgotando").
5. **CTA (sempre por último)** — invariável: "clica no botão aqui embaixo e garante o seu também".

Vídeos curtos (~10s) comprimem pra 3 beats: Gancho → Benefício/Oferta → CTA. Os longos (~14s) usam os 5.
CTA é SEMPRE o último e SEMPRE aponta pro botão embaixo.

## Ritmo
- 3 a 5 beats falados em 12-14s. ~2-4s por beat. Corte a cada ~1,5-3s.
- Começa forte (gancho no 1º segundo), fecha em CTA. Sem introdução lenta, sem despedida.

## Como isso vira cena no gerador (mapa)
Cada BEAT = 1 cena (keyframe + clipe i2v de 2-4s). Um anúncio de 12-14s = 4-6 cenas.
- Gancho: rosto na câmera (produto pode nem aparecer ainda) OU produto erguido + 1ª frase de impacto.
- Reação/Prova + Demo: pessoa usando o produto (borrifa / veste) — enquadramento busto ou mãos.
- Benefício: produto herói perto do rosto, ou close do produto.
- Oferta/Escassez: produto na mão, expressão de urgência.
- CTA: pessoa apontando pra baixo (botão), produto em cena.
Manter a MESMA pessoa, MESMA roupa, MESMO cômodo em todas as cenas (consistência de avatar).
