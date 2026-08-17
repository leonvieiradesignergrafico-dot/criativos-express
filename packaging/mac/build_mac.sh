#!/usr/bin/env bash
#
# build_mac.sh — build ponta a ponta do Ads Express.app num Mac.
#
# Faz: cria/usa uma venv, instala as dependências (incluindo pyobjc + pyinstaller),
# gera o ícone .icns e roda o PyInstaller com o spec do Mac. Ao final você tem
# "dist/Ads Express.app".
#
# Uso:
#   bash packaging/mac/build_mac.sh
#
# Variáveis de ambiente opcionais:
#   ADSEXPRESS_ARCH=universal2|arm64|x86_64   (default universal2)
#   ADSEXPRESS_VERSION=1.0.0                   (default 1.0.0)
#   ADSEXPRESS_PY=python3.11                   (interpretador base p/ a venv)
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

ARCH="${ADSEXPRESS_ARCH:-universal2}"
VERSION="${ADSEXPRESS_VERSION:-1.0.0}"
PYBASE="${ADSEXPRESS_PY:-python3}"
VENV="$ROOT/.venv-mac"

echo "======================================================================"
echo " Ads Express — build macOS"
echo "   raiz     : $ROOT"
echo "   arch     : $ARCH"
echo "   versão   : $VERSION"
echo "   python   : $PYBASE  ($($PYBASE --version 2>&1))"
echo "======================================================================"

# 0) Sanidade: estamos num Mac?
if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERRO: este script só roda no macOS (uname != Darwin)." >&2
  exit 1
fi

# 0.1) Aviso de universal2: o Python precisa ser universal, senão o build quebra.
if [ "$ARCH" = "universal2" ]; then
  PY_ARCHS="$("$PYBASE" -c 'import platform,subprocess,sys;print(subprocess.check_output(["file","-b",sys.executable]).decode())' 2>/dev/null || true)"
  if ! echo "$PY_ARCHS" | grep -qi "universal"; then
    echo "AVISO: seu '$PYBASE' talvez NÃO seja universal2 ($PY_ARCHS)."
    echo "       Se o PyInstaller falhar com 'not a fat binary', use o Python universal2"
    echo "       do instalador oficial python.org, ou builde por arquitetura:"
    echo "           ADSEXPRESS_ARCH=arm64  bash packaging/mac/build_mac.sh"
    echo "           ADSEXPRESS_ARCH=x86_64 bash packaging/mac/build_mac.sh   (num Mac Intel/Rosetta)"
    echo
  fi
fi

# 1) venv
echo "==> [1/5] Preparando venv em $VENV"
if [ ! -d "$VENV" ]; then
  "$PYBASE" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel setuptools

# 2) dependências
echo "==> [2/5] Instalando dependências"
# pyobjc-core + frameworks Cocoa/WebKit são o backend de janela do pywebview no Mac.
python -m pip install \
  pyinstaller \
  pywebview \
  pyobjc-core \
  pyobjc-framework-Cocoa \
  pyobjc-framework-WebKit \
  pyobjc-framework-Quartz
# deps do próprio app (flask, pillow, python-dotenv, pywebview, openai)
python -m pip install -r requirements.txt

# 3) ícone
echo "==> [3/5] Gerando ícone .icns"
bash "$HERE/make_icns.sh"

# 4) limpar builds antigos e rodar o PyInstaller
echo "==> [4/5] Empacotando com PyInstaller (spec do Mac)"
rm -rf "$ROOT/build" "$ROOT/dist/Ads Express" "$ROOT/dist/Ads Express.app"
ADSEXPRESS_ARCH="$ARCH" ADSEXPRESS_VERSION="$VERSION" \
  pyinstaller packaging/AdsExpress_mac.spec --noconfirm --clean

# 5) resultado
APP="$ROOT/dist/Ads Express.app"
echo "==> [5/5] Verificando resultado"
if [ -d "$APP" ]; then
  echo
  echo "======================================================================"
  echo " OK! Bundle gerado:"
  echo "   $APP"
  echo
  echo " PRÓXIMOS PASSOS:"
  echo "   • Teste local (sem assinatura), removendo a quarentena:"
  echo "       bash packaging/mac/remove_quarantine.command   (ou dê 2 cliques nele)"
  echo "   • Distribuição bonita (DMG):"
  echo "       bash packaging/mac/create_dmg.sh"
  echo "   • Distribuição SEM aviso do Gatekeeper (recomendado p/ entregar a clientes):"
  echo "       assine + notarize -> bash packaging/mac/codesign_notarize.sh"
  echo "   • Primeira execução do usuário (Node/CLIs/ffmpeg + pasta de dados):"
  echo "       bash packaging/mac/first_run_mac.command"
  echo "======================================================================"
else
  echo "ERRO: 'dist/Ads Express.app' não foi criado. Veja o log do PyInstaller acima." >&2
  exit 1
fi
