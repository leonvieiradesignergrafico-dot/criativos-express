# Vídeo UGC — o que falta você fazer (manual)

A ferramenta agora tem dois caminhos na tela inicial: **Imagem** (como sempre) e **Vídeo UGC** (novo).
Sobe do mesmo jeito: `python desktop.py`. Todo o fluxo grátis já funciona (roteiro, keyframes,
voz edge, montagem). Faltam só as coisas que dependem de conta/chave/instalação sua:

## 1. Animar os vídeos de verdade (fal.ai) — pago, barato
Hoje o keyframe é gerado de graça, mas a ANIMAÇÃO (o vídeo se mexendo) precisa do fal.ai.
- Crie conta em https://fal.ai e ponha uns US$10 de crédito.
- Pegue a chave em https://fal.ai/dashboard/keys
- Crie o arquivo `.env` na raiz do projeto (copie de `.env.example`) e preencha:
  `FAL_KEY=cole_aqui`
- Custo: ~US$0,18 por cena de 5s (Seedance Lite). Um vídeo de 30s (6 cenas) ~ US$1.
- Trocar de modelo/velocidade: `config.toml` → `[video] modelo_api` (seedance_lite | wan_turbo | kling_std).

## 2. Voz natural paga (ElevenLabs) — opcional
O edge-tts é grátis mas robótico. Pra voz natural em PT-BR:
- Conta em https://elevenlabs.io, pegue a API key no seu perfil.
- No `.env`: `ELEVEN_API_KEY=cole_aqui`
- Na aba Avatares, escolha o engine "Paga · ElevenLabs" e clique Ouvir pra comparar com o grátis.

## 3. Motor local grátis (Wan 2.2) + voz F5 — opcional, sem custo
Anima na sua RTX 3060 Ti de graça (lento, ~10-20 min/cena). Bom pra comparar com o fal.
- Siga `scripts/instalar_wan.md` (cria o `venv_wan` com torch + baixa o modelo ~15GB na 1ª geração).
- Aponte `config.toml` → `[local] python` para o python do venv.
- Na aba Keyframes, escolha o motor "Local grátis" antes de gerar os clipes.
- Dica: no `[local]`, use o modelo Turbo com `steps = 8` pra cortar o tempo.

## Como testar o fluxo (depois da chave do fal)
1. `python desktop.py` → card "Vídeo UGC".
2. Escolha o produto, cole a copy, (opcional) escolha um avatar → "Criar roteiro".
3. Ajuste as cenas / converse com o roteirista → "Aprovar roteiro".
4. "Gerar keyframes" (grátis). Aprove/refine/regere cada cena até ficar bom.
5. "Gerar clipes" (escolha motor API ou Local) → anima só o que você aprovou.
6. "Montar vídeo final" → baixa o MP4 9:16 com narração e legenda.

Regerar 1 cena ruim custa só aquela cena. Se o fal cair no meio, use "Retomar sem pagar".
