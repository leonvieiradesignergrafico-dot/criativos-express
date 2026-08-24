# Criativos Express

Ferramenta local para gerar **criativos de anúncios** (direct response) com **GPT Image 2**,
mantendo o **produto idêntico** às fotos de referência.

- **Inteligência** (copies, ângulos, prompts de imagem) → **Claude Code** (seu plano Claude).
- **Geração das imagens** → **Codex CLI** (seu plano ChatGPT) — **custo de API = zero**.
- **Fallback opcional pago** → API `gpt-image-2` (só se você quiser).

## Duas formas de usar

**A) App desktop (recomendado) — tudo numa janela:**
```
python desktop.py
```
Abre uma janela nativa (estilo Apple) com as 3 etapas: **Copies** (chat de verdade com o
Claude), **Prompts** (editáveis) e **Criativos** (gerar + galeria com progresso ao vivo).
Copies/prompts usam seu plano Claude (`claude -p`); imagens usam seu plano ChatGPT (Codex).

**B) Terminal + skills (avançado):**
```
prompt seu ──> /gerar-copies ──> copies.md
                          └─> /gerar-prompts-imagem ──> prompts.json
                                      └─> python gerar.py <produto> ──> criativos/*.png
```

Em ambos: SEMPRE usa as fotos de `products/<produto>/referencia/` para manter o produto idêntico.

## Pré-requisitos (uma vez)

1. **Python** e dependências:
   ```
   pip install -r requirements.txt
   ```
2. **Claude Code CLI** logado (usado nas copies/prompts, via seu plano Claude):
   ```
   claude login           # o mesmo login que você já usa
   ```
3. **Codex CLI** logado com sua conta ChatGPT (geração de imagem, grátis):
   ```
   npm install -g @openai/codex
   codex login            # ou: codex login --device-auth
   codex login status     # deve dizer "Logged in using ChatGPT"
   ```
4. *(Opcional, só p/ backend pago de imagem)* copie `.env.example` → `.env` e coloque
   `OPENAI_API_KEY`, e em `config.toml` troque `backend = "api"`.

## Criar um produto

1. Duplique a pasta `products/_TEMPLATE/` com o nome do produto, ex.: `products/meu-perfume/`.
2. Preencha `config.md` (regras, tom, oferta, público, regras visuais, proibições).
3. Coloque em `contexto/` o material de apoio (página de vendas, transcrições, anúncios validados).
4. Coloque em `referencia/` **as fotos reais do produto** (obrigatório). PNG/JPEG/WEBP;
   AVIF/HEIC são convertidos automaticamente (precisa de `ffmpeg` no PATH).

## Fluxo de uso

1. **Copies** — no Claude Code, rode a skill:
   ```
   /gerar-copies  <seu prompt aqui>  (produto: meu-perfume)
   ```
   Ela define quantidade/ângulos, confirma com você, gera e salva `output/copies.md`.

2. **Prompts de imagem** — rode:
   ```
   /gerar-prompts-imagem  (produto: meu-perfume)
   ```
   Gera 1 prompt de imagem por copy e salva `output/prompts.json`.

3. **Gerar as imagens** — abra o painel:
   ```
   python painel/app.py
   ```
   Acesse http://localhost:5000, escolha o produto e clique **Gerar criativos**.
   Acompanhe a barra de progresso e os criativos aparecendo. Baixe direto da grade.

   Alternativa por terminal:
   ```
   python gerar.py meu-perfume
   python gerar.py meu-perfume --backend api   # usar a API paga
   ```

Os criativos ficam em `products/<produto>/output/criativos/`.

## Configuração (`config.toml`)
- `backend` — `"codex"` (grátis, padrão) ou `"api"` (pago).
- `size` — tamanho padrão (`1024x1024`).
- `quality` — qualidade na rota API (`low|medium|high|auto`).
- `timeout` — segundos por imagem.

## Regra absoluta
Todo criativo usa as fotos de `referencia/` e mantém o produto **idêntico** ao real —
só variando ângulo, iluminação, fundo e ambientação. Essa regra é injetada em toda geração.

## Diagnóstico rápido (teste de fumaça)
Antes de rodar um pipeline inteiro pra descobrir no último passo que algo quebrou, dá pra
pedir o diagnóstico completo ao próprio app (10s, não gasta geração):

```bash
# Mac
"/Applications/Ads Express.app/Contents/MacOS/Ads Express" --smoke
```
```powershell
# Windows
& "$env:LOCALAPPDATA\Programs\Ads Express\Ads Express.exe" --smoke
```

Ele checa: bundle de CAs/TLS (a causa do `CERTIFICATE_VERIFY_FAILED` no Mac), HTTPS real
contra Vertex/Anthropic/npm, todos os imports do bundle, assets, pasta gravável, rotas do
Flask, as CLIs (node/claude/codex/ffmpeg/gcloud) e o token do Google ponta a ponta.
`FALHA` = quebrado; `AVISO` = depende da máquina (ffmpeg ausente, login não feito).

Esse mesmo teste roda no CI (`.github/workflows/build-mac.yml`) em cima do `.app` já
buildado, **antes** de publicar o `.dmg` — build que não passa não vira release.
