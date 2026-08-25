#!/usr/bin/env bash
#
# instalar_tudo.command — ÚNICO arquivo que você precisa rodar num Mac novo (ou depois
# de perder o build antigo). Dois cliques no Finder (ou `bash instalar_tudo.command` no
# Terminal) e ele garante TUDO, do zero, sem precisar de mais nada instalado antes:
#
#   1. Xcode Command Line Tools (compilador/codesign/iconutil)
#   2. Homebrew (gerenciador de pacotes do Mac)
#   3. Python 3.11+ (via Homebrew, se não houver um já bom o suficiente)
#   4. Node.js + CLIs de IA (claude/codex) + ffmpeg + gcloud + logins
#      (delega pro first_run_mac.command, que já faz isso — não duplica)
#   5. Builda o Ads Express.app (build_mac.sh)
#   6. Empacota o Ads Express.dmg (create_dmg.sh)
#   7. Abre a pasta com o resultado pronto pra arrastar pra Aplicativos
#
# Idempotente: pode rodar de novo quantas vezes quiser (ex.: depois de puxar código novo
# do GitHub), ele só instala o que ainda falta e rebuilda o app com o código atual.
#
set -uo pipefail

BOLD=$'\033[1m'; GREEN=$'\033[92m'; RED=$'\033[91m'; YEL=$'\033[93m'; CYAN=$'\033[96m'; GRAY=$'\033[90m'; RST=$'\033[0m'
titulo(){ printf "\n%s\n  %s%s%s\n%s\n" "${GRAY}────────────────────────────────────────────────────────────${RST}" "$BOLD" "$1" "$RST" "${GRAY}────────────────────────────────────────────────────────────${RST}"; }
ok(){    printf "  ${GREEN}✓${RST} %s\n" "$1"; }
falha(){ printf "  ${RED}✗${RST} %s\n" "$1"; }
aviso(){ printf "  ${YEL}!${RST} %s\n" "$1"; }
passo(){ printf "  ${CYAN}→${RST} %s\n" "$1"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

printf "\n${CYAN}  ╔══════════════════════════════════════════════════════════╗${RST}\n"
printf "${CYAN}  ║   Ads Express · Instalar TUDO no Mac (do zero)            ║${RST}\n"
printf "${CYAN}  ╚══════════════════════════════════════════════════════════╝${RST}\n"
echo   "  Isto prepara o Mac inteiro e gera um Ads Express.dmg novo. Pode demorar"
echo   "  alguns minutos na primeira vez (compiladores + dependências)."

if [ "$(uname -s)" != "Darwin" ]; then
  falha "Este instalador só roda no macOS."
  exit 1
fi

# ---------------------------------------------------------------------------
# 0) Xcode Command Line Tools — necessário pra codesign/iconutil/compilar nativos.
# ---------------------------------------------------------------------------
titulo "1/6 · Xcode Command Line Tools"
if xcode-select -p >/dev/null 2>&1 && command -v clang >/dev/null 2>&1; then
  ok "Já instaladas."
else
  falha "Não encontradas — são obrigatórias pra empacotar o app."
  passo "Abrindo o instalador oficial da Apple. Uma janela vai aparecer: clique em"
  passo "\"Instalar\" e espere terminar (alguns minutos, precisa de internet)."
  xcode-select --install 2>/dev/null || true
  passo "Aguardando você concluir a instalação na janela que abriu (até ~20 min)..."
  _tentativas=0
  until command -v clang >/dev/null 2>&1; do
    sleep 5
    _tentativas=$((_tentativas + 1))
    if [ "$_tentativas" -ge 240 ]; then
      falha "Não detectei a instalação terminar depois de ~20 min."
      aviso "Confira se a janela da Apple ainda está aberta/travada, conclua a instalação"
      aviso "manualmente e rode este arquivo (instalar_tudo.command) de novo."
      exit 1
    fi
  done
  ok "Command Line Tools instaladas."
fi

# ---------------------------------------------------------------------------
# 1) Homebrew — precisa ANTES do Python (e o first_run_mac.command também usa).
# ---------------------------------------------------------------------------
titulo "2/6 · Homebrew"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$b" ] && eval "$("$b" shellenv)" && break
done
if command -v brew >/dev/null 2>&1; then
  ok "Homebrew encontrado: $(command -v brew)"
else
  falha "Homebrew não encontrado — instalando agora (pode pedir sua senha do Mac)..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || { falha "Falha ao instalar o Homebrew. Instale manualmente em https://brew.sh e rode este arquivo de novo."; exit 1; }
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)" && break
  done
  ok "Homebrew instalado."
fi

# ---------------------------------------------------------------------------
# 2) Python 3.11+ — o build_mac.sh precisa de um python3 "de verdade" (>=3.11).
# ---------------------------------------------------------------------------
titulo "3/6 · Python 3.11+"
PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    maj="$("$cand" -c 'import sys;print(sys.version_info[0])' 2>/dev/null || echo 0)"
    min="$("$cand" -c 'import sys;print(sys.version_info[1])' 2>/dev/null || echo 0)"
    if [ "$maj" -eq 3 ] && [ "$min" -ge 11 ]; then PY="$cand"; break; fi
  fi
done
if [ -n "$PY" ]; then
  ok "Python encontrado: $PY ($("$PY" --version 2>&1))"
else
  falha "Nenhum Python 3.11+ encontrado — instalando via Homebrew..."
  brew install python@3.12 || { falha "Falha ao instalar o Python. Rode 'brew install python@3.12' manualmente."; exit 1; }
  for cand in python3.12 python3; do
    command -v "$cand" >/dev/null 2>&1 && { PY="$cand"; break; }
  done
  ok "Python instalado: $PY ($("$PY" --version 2>&1))"
fi
export ADSEXPRESS_PY="$PY"

# O build_mac.sh builda "universal2" (arm64+Intel) por padrão — mas só o instalador
# oficial do python.org é universal2; o Python do Homebrew é SEMPRE de arquitetura
# única (a do próprio Mac). Buildar "universal2" com um Python não-universal quebra o
# PyInstaller ("not a fat binary"). Detecta e ajusta pro que realmente vai funcionar
# NESTE Mac, sem exigir que você instale o Python "certo" separadamente.
if [ -z "${ADSEXPRESS_ARCH:-}" ]; then
  PY_FILE_INFO="$("$PY" -c 'import subprocess,sys;print(subprocess.check_output(["file","-b",sys.executable]).decode())' 2>/dev/null || true)"
  if echo "$PY_FILE_INFO" | grep -qi universal; then
    export ADSEXPRESS_ARCH="universal2"
    ok "Python é universal2 — build cobrindo Apple Silicon + Intel."
  else
    export ADSEXPRESS_ARCH="$(uname -m)"   # arm64 (Apple Silicon) ou x86_64 (Intel)
    aviso "Python não é universal2 — build só pra esta arquitetura ($ADSEXPRESS_ARCH)."
    aviso "Funciona normalmente NESTE Mac. Pra gerar um app que roda nos dois tipos de"
    aviso "chip, instale o Python universal2 oficial (python.org) e rode de novo."
  fi
fi

# ---------------------------------------------------------------------------
# 3) Node/CLIs (claude, codex)/ffmpeg/gcloud + logins — reaproveita o assistente
#    de primeira execução, que já faz exatamente isso (não duplica lógica).
# ---------------------------------------------------------------------------
titulo "4/6 · Node.js, CLIs de IA (claude/codex), ffmpeg, gcloud + logins"
ADSEXPRESS_NO_PAUSE=1 bash "$HERE/first_run_mac.command"

# ---------------------------------------------------------------------------
# 4) Build do .app (usa o Python garantido acima)
# ---------------------------------------------------------------------------
titulo "5/6 · Empacotando o app + o instalador premium"
bash "$HERE/build_mac.sh" || { falha "Build falhou — veja o log do PyInstaller acima."; exit 1; }

# ---------------------------------------------------------------------------
# 5) Empacota o .dmg (que entrega o instalador premium)
# ---------------------------------------------------------------------------
titulo "6/6 · Gerando o Ads Express.dmg (com o instalador dentro)"
bash "$HERE/create_dmg.sh" || aviso "Não consegui gerar o .dmg — o app já está pronto em dist/ mesmo assim."

# ---------------------------------------------------------------------------
echo
VERSION="${ADSEXPRESS_VERSION:-$(cat "$ROOT/VERSION" 2>/dev/null | tr -d "[:space:]")}"
VERSION="${VERSION:-1.0.0}"
DMG="$ROOT/Ads Express $VERSION.dmg"
printf "${GREEN}══════════════════════════════════════════════════════════════${RST}\n"
if [ -f "$DMG" ]; then
  # Copia o .dmg pra Área de Trabalho — instalador limpo, no mesmo lugar de sempre.
  DMG_DESKTOP="$HOME/Desktop/Ads Express.dmg"
  cp -f "$DMG" "$DMG_DESKTOP" 2>/dev/null && DMG="$DMG_DESKTOP"
  printf "${GREEN}  Tudo pronto! Instalador na Área de Trabalho: %s${RST}\n" "$DMG"
  # Abre o .dmg (monta e mostra o "Ads Express Installer"), NUNCA a pasta do repositório.
  open "$DMG"
  echo
  echo "  Na janela que abriu, dê DOIS CLIQUES em \"Ads Express Installer\" — o assistente"
  echo "  premium cuida de tudo (copia o app pra Aplicativos, instala Node/CLIs, logins)."
  echo "  (1ª vez pode aparecer aviso de desenvolvedor: BOTÃO DIREITO -> Abrir -> Abrir.)"
  echo "  O ícone de disco temporário some quando você ejetar (⏏) depois de instalar."
else
  printf "${YEL}  App buildado em dist/, mas o .dmg não saiu. Confira os logs acima.${RST}\n"
  open "$ROOT/dist" 2>/dev/null || true
fi
printf "${GREEN}══════════════════════════════════════════════════════════════${RST}\n"
echo "  Pra distribuir/atualizar: entregue o \"Ads Express.dmg\" — o usuário só dá dois"
echo "  cliques no instalador lá dentro. Sem terminal."
echo "  Só volte a rodar este instalar_tudo.command quando o código mudar de novo."
if [ -t 0 ]; then read -r -p "$(printf '\n  Pressione ENTER para sair...')" _ || true; fi
