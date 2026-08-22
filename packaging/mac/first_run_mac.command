#!/usr/bin/env bash
#
# first_run_mac.command — assistente de PRIMEIRA EXECUÇÃO do Ads Express no Mac.
#
# Para usuários NÃO técnicos: dê DOIS CLIQUES neste arquivo. Ele prepara tudo que o
# app precisa e NÃO estraga nada já instalado (idempotente, pode rodar de novo).
#
# O que faz:
#   1. Cria a pasta de dados ~/Library/Application Support/Ads Express/ (config/ + gerados/)
#      e semeia o config.toml padrão se ainda não existir.
#   2. Confere o Homebrew (gerenciador de pacotes do Mac) e oferece instalar.
#   3. Confere o Node.js (obrigatório) e oferece instalar via Homebrew.
#   4. Instala/atualiza as CLIs: @anthropic-ai/claude-code (comando 'claude') e
#      @openai/codex (comando 'codex').
#   5. Guia os LOGINS (claude /login e codex login) — usam SEU plano, sem custo de API.
#   6. Confere o ffmpeg (opcional, só p/ o fluxo de VÍDEO) e oferece instalar.
#   7. Confere o Google Cloud SDK / gcloud (opcional, só p/ o VÍDEO Veo), oferece instalar
#      E faz o login do Google (gcloud auth login + application-default), igual claude/codex.
#   8. Grava os caminhos ABSOLUTOS de node/claude/codex/ffmpeg/gcloud num arquivo que o app
#      lê — porque um app .app do macOS NÃO herda o PATH do Terminal (ver README_MAC.md).
#
set -uo pipefail

# --- cores / helpers ----------------------------------------------------------
BOLD=$'\033[1m'; GREEN=$'\033[92m'; RED=$'\033[91m'; YEL=$'\033[93m'; CYAN=$'\033[96m'; GRAY=$'\033[90m'; RST=$'\033[0m'
titulo(){ printf "\n%s\n  %s%s%s\n%s\n" "${GRAY}────────────────────────────────────────────────────────────${RST}" "$BOLD" "$1" "$RST" "${GRAY}────────────────────────────────────────────────────────────${RST}"; }
ok(){    printf "  ${GREEN}✓${RST} %s\n" "$1"; }
falha(){ printf "  ${RED}✗${RST} %s\n" "$1"; }
aviso(){ printf "  ${YEL}!${RST} %s\n" "$1"; }
passo(){ printf "  ${CYAN}→${RST} %s\n" "$1"; }
perguntar(){ # $1 pergunta ; retorna 0=sim
  local resp; printf "  ${YEL}?${RST} %s [S/n] " "$1"; read -r resp || resp=""
  case "${resp:-s}" in s|S|sim|y|Y|yes|"") return 0;; *) return 1;; esac
}

# Pasta de dados gravável do app no macOS.
APP_SUPPORT="$HOME/Library/Application Support/Ads Express"
CONFIG_DIR="$APP_SUPPORT/config"
GERADOS_DIR="$APP_SUPPORT/gerados"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLAUDE_PKG="@anthropic-ai/claude-code"
CODEX_PKG="@openai/codex"

printf "\n${CYAN}  ╔══════════════════════════════════════════════════════════╗${RST}\n"
printf "${CYAN}  ║   Ads Express · Preparar meu Mac (primeira execução)      ║${RST}\n"
printf "${CYAN}  ╚══════════════════════════════════════════════════════════╝${RST}\n"
echo   "  Este assistente instala o que o app precisa. Pode rodar quantas vezes quiser."

# ---------------------------------------------------------------------------
# 1) Pasta de dados + config padrão
# ---------------------------------------------------------------------------
titulo "1/7 · Pasta de dados do app"
mkdir -p "$CONFIG_DIR" "$GERADOS_DIR"
ok "Pasta criada: $APP_SUPPORT"
if [ ! -f "$CONFIG_DIR/config.toml" ]; then
  # Procura o template embutido: ao lado deste .command, ou dentro do .app instalado.
  TEMPLATE=""
  for cand in \
    "$HERE/default_config/config.toml" \
    "$HERE/../default_config/config.toml" \
    "/Applications/Ads Express.app/Contents/Resources/_default_config/config.toml" \
    "/Applications/Ads Express.app/Contents/MacOS/_default_config/config.toml" \
    "$HOME/Applications/Ads Express.app/Contents/Resources/_default_config/config.toml"; do
    if [ -f "$cand" ]; then TEMPLATE="$cand"; break; fi
  done
  if [ -n "$TEMPLATE" ]; then
    cp "$TEMPLATE" "$CONFIG_DIR/config.toml"
    ok "config.toml padrão copiado de: $TEMPLATE"
  else
    # Fallback mínimo: o app sobrescreve/complementa na 1ª execução (ensure_user_config).
    cat > "$CONFIG_DIR/config.toml" <<'TOML'
# Config mínimo gerado pelo first_run_mac. O app completa o resto na 1ª execução.
[geracao]
backend = "codex"
size = "1024x1024"
timeout = 600
workers = 6
[app]
ffmpeg = ""
TOML
    aviso "Template embutido não encontrado — gravei um config.toml mínimo (o app completa depois)."
  fi
else
  ok "config.toml já existe — mantido (nada sobrescrito)."
fi

# ---------------------------------------------------------------------------
# 2) Homebrew
# ---------------------------------------------------------------------------
titulo "2/7 · Homebrew (gerenciador de pacotes do Mac)"
# Em Apple Silicon o brew vive em /opt/homebrew; em Intel, /usr/local.
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$b" ] && eval "$("$b" shellenv)" && break
done
if command -v brew >/dev/null 2>&1; then
  ok "Homebrew encontrado: $(command -v brew)"
else
  falha "Homebrew não encontrado (facilita instalar Node e ffmpeg)."
  if perguntar "Instalar o Homebrew agora? (abre a instalação oficial)"; then
    passo "Instalando Homebrew — pode pedir sua senha do Mac..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || aviso "Instalação do Homebrew não concluída."
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      [ -x "$b" ] && eval "$("$b" shellenv)" && break
    done
  else
    aviso "Sem o Homebrew você pode instalar o Node manualmente em https://nodejs.org (versão LTS)."
  fi
fi

# ---------------------------------------------------------------------------
# 3) Node.js
# ---------------------------------------------------------------------------
titulo "3/7 · Node.js (obrigatório — as CLIs rodam sobre ele)"
if command -v node >/dev/null 2>&1; then
  ok "Node.js: $(node --version)   npm: $(npm --version 2>/dev/null || echo '?')"
else
  falha "Node.js não encontrado."
  if command -v brew >/dev/null 2>&1 && perguntar "Instalar o Node via Homebrew agora?"; then
    brew install node || aviso "Falha ao instalar node via brew."
  else
    aviso "Instale o Node LTS em https://nodejs.org e rode este assistente de novo."
  fi
fi

# ---------------------------------------------------------------------------
# 4) CLIs claude + codex
# ---------------------------------------------------------------------------
instalar_cli(){ # $1 comando ; $2 pacote npm
  local cmd="$1" pkg="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "'$cmd' já instalado: $("$cmd" --version 2>/dev/null | head -n1)"
    return 0
  fi
  falha "'$cmd' não encontrado."
  if command -v npm >/dev/null 2>&1 && perguntar "Instalar '$cmd' agora (npm install -g $pkg)?"; then
    npm install -g "$pkg" && ok "'$cmd' instalado." || { falha "Falhou. Rode manualmente:"; echo "        npm install -g $pkg"; }
  else
    aviso "Para instalar depois: npm install -g $pkg"
  fi
}
titulo "4/7 · CLIs de IA (Claude Code + Codex)"
instalar_cli "claude" "$CLAUDE_PKG"
instalar_cli "codex"  "$CODEX_PKG"

# ---------------------------------------------------------------------------
# 5) Logins (usam SEU plano — custo de API = zero)
# ---------------------------------------------------------------------------
titulo "5/7 · Login das CLIs (usa seu plano Claude e ChatGPT)"
if command -v claude >/dev/null 2>&1; then
  if perguntar "Fazer/checar o login do Claude agora? (abre o navegador)"; then
    passo "Vai abrir o Claude. Se pedir, digite ${BOLD}/login${RST} e conclua no navegador."
    passo "Quando terminar, digite ${BOLD}/exit${RST} (ou feche a janela) para CONTINUAR a instalação."
    # ARMADILHA: o 'claude /login' entra no modo interativo e NÃO sai sozinho. Se o
    # usuário apertar Ctrl+C pra sair, o SIGINT vai pro grupo inteiro e mata ESTE
    # instalador — pulando o login do Codex e do Google (era o bug do "não pede codex").
    # Blindagem: ignoramos INT enquanto o claude roda, então sair do claude (Ctrl+C ou
    # /exit) devolve o controle pra cá em vez de abortar tudo.
    trap '' INT
    claude /login || true
    trap - INT
    ok "Login do Claude concluído — seguindo para o próximo."
  fi
else
  aviso "Instale a CLI 'claude' antes de logar."
fi
if command -v codex >/dev/null 2>&1; then
  if perguntar "Fazer/checar o login do Codex (ChatGPT) agora? (abre o navegador)"; then
    passo "Vai abrir o navegador pro login do Codex. Conclua e volte aqui."
    # Mesma blindagem contra Ctrl+C que mataria o instalador no meio do caminho.
    trap '' INT
    codex login || true
    trap - INT
    ok "Login do Codex concluído — seguindo para o próximo."
  fi
else
  aviso "Instale a CLI 'codex' antes de logar."
fi

# ---------------------------------------------------------------------------
# 6) ffmpeg (opcional)
# ---------------------------------------------------------------------------
titulo "6/7 · ffmpeg (opcional — só para o fluxo de VÍDEO)"
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg: $(ffmpeg -version 2>/dev/null | head -n1)"
else
  aviso "ffmpeg não encontrado (só é necessário para gerar VÍDEO, não imagem)."
  if command -v brew >/dev/null 2>&1 && perguntar "Instalar o ffmpeg via Homebrew agora?"; then
    brew install ffmpeg || aviso "Falha ao instalar ffmpeg."
  fi
fi

# ---------------------------------------------------------------------------
# 7) Google Cloud SDK / gcloud (opcional — só para o VÍDEO Veo)
# ---------------------------------------------------------------------------
titulo "7/7 · Google Cloud SDK / gcloud (opcional — só para o VÍDEO Veo)"
if command -v gcloud >/dev/null 2>&1; then
  ok "gcloud: $(gcloud --version 2>/dev/null | head -n1 || echo 'presente')"
else
  aviso "gcloud não encontrado (só é necessário para o fluxo de VÍDEO Veo/Omni, não imagem)."
  if command -v brew >/dev/null 2>&1 && perguntar "Instalar o Google Cloud SDK via Homebrew agora?"; then
    brew install --cask google-cloud-sdk || aviso "Falha ao instalar o google-cloud-sdk."
    # O cask instala em /opt/homebrew/... mas o binário pode não estar no PATH ainda
    # nesta mesma sessão; tenta achar pra conseguir logar logo em seguida.
    if ! command -v gcloud >/dev/null 2>&1; then
      for g in /opt/homebrew/share/google-cloud-sdk/bin/gcloud \
               /opt/homebrew/bin/gcloud \
               /usr/local/share/google-cloud-sdk/bin/gcloud \
               /usr/local/bin/gcloud; do
        [ -x "$g" ] && export PATH="$(dirname "$g"):$PATH" && break
      done
    fi
  else
    aviso "Instalação manual do gcloud: https://cloud.google.com/sdk/docs/install"
  fi
fi
# Login do Google — igual claude/codex: pergunta e executa aqui mesmo (antes só dava dica).
if command -v gcloud >/dev/null 2>&1; then
  if perguntar "Fazer/checar o login do Google Cloud agora? (abre o navegador)"; then
    passo "Vai abrir o navegador pro login do Google. Use a conta com acesso ao projeto Veo."
    # Mesma blindagem contra Ctrl+C que mataria o instalador no meio do caminho.
    trap '' INT
    gcloud auth login || aviso "Login do Google Cloud não concluído."
    # O Veo/Vertex usa Application Default Credentials — loga também pra as libs acharem.
    gcloud auth application-default login || aviso "ADC (application-default) não concluído."
    trap - INT
    ok "Login do Google Cloud concluído."
  fi
else
  aviso "Instale o gcloud antes de logar no Google Cloud."
fi
passo "O VÍDEO também precisa do VEO_PROJECT (id do projeto GCP) no config."

# ---------------------------------------------------------------------------
# PATH do .app: grava os caminhos absolutos que o app deve usar.
# (Um app do macOS NÃO herda o PATH do shell — ver README_MAC.md / flag p/ o main agent.)
# ---------------------------------------------------------------------------
titulo "Extra · Gravando os caminhos das ferramentas para o app"
CLI_ENV="$CONFIG_DIR/cli_paths.env"
{
  echo "# Caminhos ABSOLUTOS detectados pelo first_run_mac. O app deve adicionar estes"
  echo "# diretórios ao PATH em runtime (apps .app do macOS não herdam o PATH do Terminal)."
  for tool in node npm claude codex ffmpeg gcloud; do
    p="$(command -v "$tool" 2>/dev/null || true)"
    if [ -n "$p" ]; then
      # macOS traz bash 3.2 (sem ${var^^}); usa tr p/ maiúsculas.
      up="$(printf '%s' "$tool" | tr '[:lower:]' '[:upper:]')"
      echo "${up}_PATH=$p"
    fi
  done
} > "$CLI_ENV"
ok "Salvo em: $CLI_ENV"

# ---------------------------------------------------------------------------
titulo "Resumo"
faltou=0
for t in node claude codex; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t: pronto"; else aviso "$t: pendente"; faltou=1; fi
done
command -v ffmpeg >/dev/null 2>&1 && ok "ffmpeg: pronto (vídeo)" || aviso "ffmpeg: pendente (só vídeo)"
command -v gcloud >/dev/null 2>&1 && ok "gcloud: pronto (vídeo Veo)" || aviso "gcloud: pendente (só vídeo Veo)"
echo
if [ "$faltou" -eq 0 ]; then
  printf "  ${GREEN}Tudo pronto! Pode abrir o Ads Express e gerar criativos.${RST}\n"
else
  printf "  ${YEL}Faltam itens essenciais acima. Resolva e rode este assistente de novo.${RST}\n"
fi

# ADSEXPRESS_NO_PAUSE=1 é setado pelo instalar_tudo.command quando ele chama este
# assistente como uma ETAPA (não a última) do fluxo — sem isso o usuário veria "Pressione
# ENTER para sair" no MEIO do processo, achando que tudo já tinha terminado.
if [ -t 0 ] && [ -z "${ADSEXPRESS_NO_PAUSE:-}" ]; then
  read -r -p "$(printf '\n  Pressione ENTER para sair...')" _ || true
fi
