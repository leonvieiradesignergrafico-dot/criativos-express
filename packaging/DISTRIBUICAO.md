# Ads Express — Distribuição (Windows + Mac)

Guia único pra levar o app pra um PC novo e rodar de verdade. O app é uma janela nativa
(pywebview) que sobe um servidor local e usa os CLIs **Claude Code** e **Codex** por baixo.

## Onde ficam os dados (os dois SOs)
- **Código-fonte** (`python desktop.py`): `config/` e `gerados/` na própria pasta do projeto.
- **Windows empacotado**: `config/` e `gerados/` **ao lado do `.exe`** (instalação per-user, gravável).
- **macOS empacotado**: `~/Library/Application Support/Ads Express/` (um `.app` em /Applications é
  só-leitura — regra do Mac; por isso os dados vão pro Application Support).

Estrutura:
```
config/    config.toml, .env, products/<cliente>/<produto>/, avatares/, influenciadores/
gerados/   <cliente|_sem-cliente>/<produto>/<DD-MM-AAAA>/   (só as imagens geradas)
```

---

## Windows — PRONTO (buildado e testado)

Artefatos já gerados (nesta máquina):
- `packaging/Output/AdsExpress-Setup-1.0.0.exe` — **instalador** (per-user, sem admin).
- `dist/Ads Express/Ads Express.exe` — o app (sem janela de CMD, com ícone).
- `dist/Setup Ads Express/` — wizard de dependências + logins.

### Levar pra um PC Windows novo
1. Copie e rode **`AdsExpress-Setup-1.0.0.exe`**. Instala em `%LOCALAPPDATA%\Programs\Ads Express`,
   cria atalhos "Ads Express" e "Setup / Reparar".
2. Rode **"Setup / Reparar"** uma vez: o wizard checa/instala **Node**, **Claude CLI**
   (`@anthropic-ai/claude-code`), **Codex CLI** (`@openai/codex`) e **ffmpeg**, e conduz os
   **logins** dos CLIs (OAuth no browser). Re-executável quando quiser.
3. Abra "Ads Express". Pronto.

### Rebuildar (depois de mudar o código)
```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1        # gera os dois .exe
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" packaging\installer_windows.iss   # gera o instalador
```

### Só mudou um prompt (`app\prompts\*.md`)? Não precisa rebuild completo
O app instalado (`%LOCALAPPDATA%\Programs\Ads Express\`) e a cópia empacotada dentro da pasta
do projeto (`Ads Express (app)\`) leem os prompts de uma cópia própria, **não** da fonte —
editar `app\prompts\` não afeta essas duas cópias sozinho (drift real já aconteceu, 3 dias
de defasagem). Pra sincronizar só os `.md` sem rodar o PyInstaller inteiro:
```powershell
powershell -ExecutionPolicy Bypass -File packaging\sync-prompts.ps1
```

---

## macOS — KIT COMPLETO (precisa rodar num Mac)

⚠️ **Não dá pra buildar o `.app` no Windows** — binário de macOS se compila num Mac. O kit abaixo
está inteiro e com os *quirks* do Mac já resolvidos; num Mac é praticamente um comando.
Guia detalhado: **`packaging/README_MAC.md`**.

### Distribuição interna (sem assinar) — rápido
```bash
bash packaging/mac/build_mac.sh      # venv + deps + .icns + PyInstaller -> dist/Ads Express.app
bash packaging/mac/create_dmg.sh     # gera o .dmg (com atalho pra Applications + removedor de quarentena)
```
O `build_mac.sh` já **assina o app ad-hoc** (grátis): na 1ª abertura o usuário faz só
**botão direito → Abrir → Abrir** (sem Terminal). Depois roda `first_run_mac.command`
(Homebrew/Node/CLIs/logins/ffmpeg). Plano B, se algum Mac reclamar de "danificado":
`remove_quarantine.command` (incluído no DMG).

### Distribuição pública (assinada + notarizada) — precisa de você
Requer **conta Apple Developer** ($99/ano): cert "Developer ID Application" + senha de app.
```bash
bash packaging/mac/build_mac.sh
export DEVELOPER_ID="Developer ID Application: SEU NOME (TEAMID)" APPLE_ID=... TEAM_ID=... APPLE_PASSWORD=...
bash packaging/mac/codesign_notarize.sh
bash packaging/mac/create_dmg.sh
```

### Quirks do Mac já tratados no código/kit
- **App de janela não herda o PATH do terminal** → `workspace.py` prependa `/opt/homebrew/bin`,
  `/usr/local/bin`, `~/.npm-global/bin` ao PATH no macOS (senão os CLIs "somem").
- **`http://127.0.0.1` bloqueado (ATS)** → exceção `NSAllowsLocalNetworking` no `Info.plist`.
- **`.app` só-leitura** → dados em `~/Library/Application Support/Ads Express/`.
- **"App está danificado" (Gatekeeper)** → evitado pelo ad-hoc signing do `build_mac.sh`
  (basta botão direito → Abrir); `remove_quarantine.command` é o plano B, notarização o definitivo.
- **Apple Silicon vs Intel** → `universal2` no spec.

---

## O que o app precisa em runtime (os dois SOs)
- **Node.js** + **Claude Code CLI** + **Codex CLI** (logados) — o wizard/first-run cuida.
- **ffmpeg** (só pro fluxo de vídeo).
- Chaves/planos: os CLIs usam seus próprios logins; `.env` guarda o que for específico
  (ex.: `VEO_PROJECT`). O `config.toml` guarda as preferências de geração.
