# Ads Express — Empacotamento para macOS

Guia definitivo para gerar, assinar e distribuir o **Ads Express.app** no Mac. Tudo
foi escrito para rodar num Mac (o build só pode ser feito no macOS). Cada gotcha
conhecida do macOS já vem pré-resolvida — ver o checklist no fim.

> **Importante:** o build de um `.app` PRECISA acontecer num Mac. PyInstaller não faz
> cross-compile de Windows→macOS. Os scripts abaixo assumem macOS 11+ com as
> Command Line Tools do Xcode instaladas (`xcode-select --install`).

---

## 0. Pré-requisitos (no Mac que builda)

| Item | Por quê | Como |
|------|---------|------|
| macOS 11+ (Big Sur ou mais novo) | piso do universal2 / Apple Silicon | — |
| Command Line Tools do Xcode | traz `codesign`, `iconutil`, `hdiutil`, `xcrun` | `xcode-select --install` |
| Python 3.11+ (de preferência **universal2** do python.org) | build universal (arm64+Intel) | https://www.python.org/downloads/macos/ |
| Homebrew (opcional, recomendado) | instala `node`, `ffmpeg`, `create-dmg` | https://brew.sh |
| **Só p/ assinar/notarizar:** conta paga Apple Developer (US$99/ano) | Gatekeeper sem avisos | https://developer.apple.com/programs/ |

---

## 1. Build (o caminho de 1 comando)

```bash
cd "/caminho/para/Criativos Express"
bash packaging/mac/build_mac.sh
```

Isso: cria uma venv, instala PyInstaller + pywebview + **pyobjc** (Cocoa/WebKit) +
`requirements.txt`, gera o ícone `.icns` e roda o PyInstaller com o spec do Mac.
Saída: **`dist/Ads Express.app`**.

Variáveis opcionais:

```bash
ADSEXPRESS_VERSION=1.2.0 bash packaging/mac/build_mac.sh      # muda a versão exibida
ADSEXPRESS_ARCH=arm64    bash packaging/mac/build_mac.sh      # só Apple Silicon
ADSEXPRESS_ARCH=x86_64   bash packaging/mac/build_mac.sh      # só Intel
```

### universal2 vs por-arquitetura
O default é `target_arch='universal2'` (roda em Apple Silicon **e** Intel). Isso
exige que o **Python e todas as deps binárias** (pyobjc, pillow…) sejam universais —
use o Python universal2 do python.org. Se o build reclamar de *"not a fat binary"*,
buíde por arquitetura (rode `ADSEXPRESS_ARCH=arm64` no Mac M-series e
`ADSEXPRESS_ARCH=x86_64` num Mac Intel) e distribua os dois `.dmg`.

---

## 2. Distribuir — dois caminhos

### 2A. Rápido / interno (SEM pagar) — grátis
Para você mesmo ou uma equipe pequena. O `build_mac.sh` **assina o app ad-hoc**
(`codesign --sign -`, grátis, sem conta Apple): isso troca o erro "app está
danificado" (que BLOQUEIA) pelo aviso brando de "desenvolvedor não identificado",
que o usuário contorna com um clique-direito.

```bash
bash packaging/mac/build_mac.sh           # ja sai ad-hoc-assinado
bash packaging/mac/create_dmg.sh          # gera dist/Ads Express <versão>.dmg
```

O usuário: abre o `.dmg`, arrasta **Ads Express** para **Aplicativos**, e na
**primeira** abertura faz **botão direito no app → Abrir → Abrir**. Sem Terminal,
e o macOS lembra da decisão pras próximas vezes.

> Plano B (se algum Mac ainda insistir em "danificado"): **dois cliques no
> `remove_quarantine.command`** (incluído no DMG). Equivale a
> `xattr -dr com.apple.quarantine "/Applications/Ads Express.app"`.

### 2B. Profissional (ASSINADO + NOTARIZADO) — abre sem nenhum aviso
Requer a conta paga Apple Developer e o certificado *Developer ID Application*.

```bash
bash packaging/mac/build_mac.sh

export DEVELOPER_ID="Developer ID Application: Seu Nome (TEAMID)"
export APPLE_ID="voce@icloud.com"
export TEAM_ID="AB12CD34EF"                 # 10 caracteres
export APPLE_PASSWORD="abcd-efgh-ijkl-mnop" # senha de APP (appleid.apple.com), não a real
bash packaging/mac/codesign_notarize.sh     # assina, envia à Apple, staple

bash packaging/mac/create_dmg.sh            # DMG com o app já notarizado
```

Depois disso o cliente abre com dois cliques, **sem** aviso de "desenvolvedor não
identificado" nem de "app danificado".

#### O que você precisa ter (feito 1 vez):
1. Inscrição no Apple Developer Program (paga).
2. Certificado **Developer ID Application** criado no developer.apple.com e instalado
   no Keychain. Confira: `security find-identity -v -p codesigning`.
3. Uma **senha de app** gerada em https://appleid.apple.com (seção Segurança) — é ela
   que vai em `APPLE_PASSWORD`, nunca a senha real do Apple ID.

---

## 3. Primeira execução (usuário final)

O app depende de ferramentas externas (Node + as CLIs `claude`/`codex` + `ffmpeg`
opcional). Para um usuário não técnico, entregue junto o **`first_run_mac.command`**:
dois cliques e ele instala/verifica tudo, guia os logins e cria a pasta de dados.
É idempotente (pode rodar de novo sem estragar nada).

```bash
bash packaging/mac/first_run_mac.command
```

Ele:
1. cria `~/Library/Application Support/Ads Express/` (`config/` + `gerados/`) e semeia o `config.toml`;
2. confere/instala **Homebrew** e **Node.js**;
3. instala as CLIs: `@anthropic-ai/claude-code` (→ `claude`) e `@openai/codex` (→ `codex`);
4. guia os logins (`claude /login`, `codex login`) — usam o **plano** do usuário, sem custo de API;
5. confere/instala o **ffmpeg** (só p/ vídeo);
6. grava os caminhos absolutos das ferramentas em `config/cli_paths.env` (ver gotcha do PATH).

---

## 4. Onde os dados vivem (macOS)

Um `.app` dentro de `/Applications` é **só-leitura** — não pode gravar ao lado de si
mesmo (diferente do Windows, onde `config/` e `gerados/` ficam junto do `.exe`). No
Mac tudo gravável vai para:

```
~/Library/Application Support/Ads Express/
    config/        <- config.toml, .env, produtos, avatares, prompts.json, status.json, ...
    gerados/       <- imagens de criativo geradas
```

> **FLAG p/ o agente principal (workspace.py):** hoje o `workspace.py` define
> `ROOT = Path(sys.executable).parent` quando congelado — no Mac isso cai DENTRO do
> bundle só-leitura. É preciso, **quando `sys.platform == 'darwin'` e frozen**, apontar
> `CONFIG_DIR`/`GERADOS_DIR` para `~/Library/Application Support/Ads Express/`. O
> `BUNDLE_DIR`/`_MEIPASS` (assets só-leitura) continua igual. O `ensure_user_config()`
> já copia o template — só precisa que `CONFIG_DIR` seja o caminho gravável acima.

---

## 5. Checklist de gotchas do macOS (todos pré-resolvidos)

| # | Gotcha | Como está resolvido |
|---|--------|---------------------|
| 1 | **ATS bloqueia `http://127.0.0.1:5000`** (WebKit recusa HTTP local → janela em branco) | `Info.plist` do spec com `NSAppTransportSecurity → NSAllowsLocalNetworking = true` |
| 2 | **App não assinado "está danificado"** (Gatekeeper + quarantine) | `remove_quarantine.command` (2 cliques) para o caminho unsigned; ou `codesign_notarize.sh` para o caminho oficial |
| 3 | **Gatekeeper / notarização** | `codesign_notarize.sh`: `codesign --deep --options runtime` + `notarytool submit --wait` + `stapler staple`, com `entitlements.plist` (hardened runtime) |
| 4 | **Apple Silicon vs Intel** | `target_arch='universal2'` por default; `ADSEXPRESS_ARCH=arm64/x86_64` para builds por arquitetura |
| 5 | **Backend de janela do pywebview** | hidden imports de `webview.platforms.cocoa` + pyobjc (`objc`, `Foundation`, `AppKit`, `WebKit`, `Quartz`); `build_mac.sh` instala `pyobjc-framework-Cocoa/WebKit` |
| 6 | **GUI `.app` NÃO herda o PATH do Terminal** → não acha `node`/`claude`/`codex`/`ffmpeg` | ver seção 6 abaixo (grande) |
| 7 | **`.app` é só-leitura** → não grava `config/`/`gerados/` ao lado | dados em `~/Library/Application Support/Ads Express/` (seção 4) |
| 8 | **Ícone** | `make_icns.sh` (`iconutil -c icns`) + fallback Pillow; embutido via `icon=...icns` e no `Info.plist` |
| 9 | **`iconutil`/`hdiutil` inexistem no Windows** | todo o kit roda no Mac; `create_dmg.sh` usa `create-dmg` se houver, senão `hdiutil` |
| 10 | **Hardened runtime mata libs de terceiros** (pyobjc/pillow não assinadas pelo seu Team) | `entitlements.plist` com `disable-library-validation`, `allow-jit`, `allow-unsigned-executable-memory` |

---

## 6. O PATH do `.app` (o gotcha nº 1 na prática) — leia com atenção

**Apps `.app` do macOS abertos pelo Finder/Dock NÃO herdam o PATH do seu shell**
(`~/.zshrc` etc.). O launchd dá a eles um PATH mínimo (`/usr/bin:/bin:/usr/sbin:/sbin`).
Resultado: `shutil.which("node"|"claude"|"codex"|"ffmpeg")` retorna `None` DENTRO do
app empacotado, mesmo com tudo instalado — e a geração falha "sem motivo".

As CLIs costumam morar em lugares que **não** estão nesse PATH mínimo:
- Apple Silicon (Homebrew): `/opt/homebrew/bin`
- Intel (Homebrew): `/usr/local/bin`
- npm global do usuário: `~/.npm-global/bin`, ou `$(npm prefix -g)/bin`
- nvm: `~/.nvm/versions/node/<versão>/bin`

### Duas defesas (o `first_run_mac.command` já prepara a primeira):
1. **`config/cli_paths.env`** — o `first_run_mac.command` detecta os caminhos ABSOLUTOS
   de `node/npm/claude/codex/ffmpeg` (rodando num Terminal com PATH completo) e grava:
   ```
   NODE_PATH=/opt/homebrew/bin/node
   CLAUDE_PATH=/opt/homebrew/bin/claude
   CODEX_PATH=/Users/voce/.npm-global/bin/codex
   FFMPEG_PATH=/opt/homebrew/bin/ffmpeg
   ```
2. **Probe de PATH em runtime** — o app deve, no boot (macOS), acrescentar os diretórios
   comuns ao `os.environ["PATH"]` e/ou ler o `cli_paths.env` acima.

### ⚑ FLAG p/ o agente principal (mudança nas pontes / boot)
Eu **não** posso editar `desktop.py`, `workspace.py` nem `app/*` (escopo travado). Para
o Mac funcionar de primeira, o agente principal precisa, **no macOS**, garantir o PATH
ANTES de qualquer `shutil.which(...)`/subprocess. Sugestão mínima (no boot do app):

```python
import os, sys
if sys.platform == "darwin":
    extra = ["/opt/homebrew/bin", "/usr/local/bin",
             os.path.expanduser("~/.npm-global/bin"),
             os.path.expanduser("~/.nvm/current/bin")]
    # opcional: ler ~/Library/Application Support/Ads Express/config/cli_paths.env
    cur = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([p for p in extra if os.path.isdir(p)] + [cur])
```

Isso conserta os quatro pontos que hoje dependem do PATH:
`app/claude_bridge._claude_exe`, `backends/codex_backend._codex_cmd_base`,
`app/codex_text_bridge` e o `ffmpeg` do `gerar.py`. (No Windows nada muda — o guard é
`sys.platform == "darwin"`.) Alternativamente, resolver cada CLI por caminho absoluto
lendo o `cli_paths.env`.

---

## 7. Arquivos deste kit (todos em `packaging/`)

| Arquivo | Papel |
|---------|-------|
| `AdsExpress_mac.spec` | spec do PyInstaller p/ o bundle `.app` (Info.plist, ATS, universal2, hidden imports Cocoa/pyobjc) |
| `mac/make_icns.sh` | gera `icons/AdsExpress.icns` do iconset (`iconutil`), com fallback Pillow |
| `mac/build_mac.sh` | build ponta a ponta (venv → deps → ícone → PyInstaller → `dist/Ads Express.app`) |
| `mac/codesign_notarize.sh` | assina (hardened runtime) + notariza + staple |
| `mac/entitlements.plist` | entitlements do hardened runtime p/ a notarização |
| `mac/remove_quarantine.command` | libera o app não assinado (2 cliques) |
| `mac/create_dmg.sh` | gera o `.dmg` (create-dmg ou hdiutil) com atalho p/ Aplicativos |
| `mac/first_run_mac.command` | assistente de 1ª execução (Node/CLIs/ffmpeg + pasta de dados) |
| `README_MAC.md` | este guia |

---

## 8. Ordem de release (resumo)

**Unsigned (interno):**
```bash
bash packaging/mac/build_mac.sh
bash packaging/mac/create_dmg.sh
# entregar o .dmg + instruir o remove_quarantine.command + first_run_mac.command
```

**Signed/notarized (público):**
```bash
bash packaging/mac/build_mac.sh
export DEVELOPER_ID=... APPLE_ID=... TEAM_ID=... APPLE_PASSWORD=...
bash packaging/mac/codesign_notarize.sh
bash packaging/mac/create_dmg.sh
# entregar o .dmg (abre sem avisos) + first_run_mac.command
```
