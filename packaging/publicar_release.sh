#!/usr/bin/env bash
#
# publicar_release.sh — publica os instaladores como uma GitHub Release.
#
# POR QUÊ: binários grandes (.exe/.dmg) NÃO ficam no git (ver .gitignore), senão o
# repositório incha pra sempre. O jeito certo de distribuir é uma RELEASE: uma página
# de download onde o usuário pega só o instalador do sistema dele (Windows ou Mac).
# Este script cria/atualiza essa Release e sobe os instaladores que achar NESTA máquina.
#
# FLUXO (dois sistemas, mesma Release):
#   • No Windows, depois de gerar o .exe:   bash packaging/publicar_release.sh
#   • No Mac, depois de gerar o .dmg:        bash packaging/publicar_release.sh
#   Rode nos dois — cada um sobe o instalador do seu SO para a MESMA Release.
#
# REQUISITOS: gh (GitHub CLI) autenticado na conta dona do repositório.
#   Instalar: https://cli.github.com   ·   Logar: gh auth login
#
set -uo pipefail

REPO="raciociniodigital/criativos-express"
ACCOUNT="raciociniodigital"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
say(){ printf "  %s\n" "$1"; }

command -v gh >/dev/null 2>&1 || {
  echo "ERRO: GitHub CLI (gh) não encontrado. Instale em https://cli.github.com"; exit 1; }

# Versão: 1º argumento, ou ADSEXPRESS_VERSION, ou o VERSION da raiz, ou o nome do .exe.
VERSION="${1:-${ADSEXPRESS_VERSION:-}}"
[ -n "$VERSION" ] || VERSION="$(cat "$ROOT/VERSION" 2>/dev/null | tr -d "[:space:]")"
if [ -z "$VERSION" ]; then
  for e in "$ROOT"/AdsExpress-Setup-*.exe; do
    [ -f "$e" ] || continue
    b="$(basename "$e")"; VERSION="${b#AdsExpress-Setup-}"; VERSION="${VERSION%.exe}"; break
  done
fi
VERSION="${VERSION:-1.1.4}"
TAG="v$VERSION"

# Garante a conta certa ativa (a dona do repositório) e restaura ao sair.
if ! gh auth status 2>&1 | grep -q "account $ACCOUNT"; then
  echo "ERRO: a conta '$ACCOUNT' não está logada no gh."
  echo "      Rode uma vez:  gh auth login   (e entre com a conta $ACCOUNT)"
  exit 1
fi
PREV="$(gh api user -q .login 2>/dev/null || echo '')"
gh auth switch --user "$ACCOUNT" >/dev/null 2>&1 || true
restore(){ [ -n "${PREV:-}" ] && [ "$PREV" != "$ACCOUNT" ] && gh auth switch --user "$PREV" >/dev/null 2>&1 || true; }
trap restore EXIT

# Coleta os instaladores presentes NESTA máquina (raiz do repo + Área de Trabalho).
ASSETS=()
for f in "$ROOT"/AdsExpress-Setup-*.exe "$ROOT"/Ads\ Express\ *.dmg \
         "$HOME/Desktop/Ads Express.dmg" "$HOME/Desktop/AdsExpress-Setup-"*.exe; do
  [ -f "$f" ] && ASSETS+=("$f")
done
if [ ${#ASSETS[@]} -eq 0 ]; then
  echo "Nenhum instalador encontrado (.exe na raiz, ou .dmg na raiz/Área de Trabalho)."
  echo "Gere primeiro:  Windows -> build   ·   Mac -> Instalar no Mac.command"
  exit 1
fi

# Cria a Release se ainda não existir.
if ! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  say "Criando Release $TAG em $REPO…"
  gh release create "$TAG" --repo "$REPO" \
    --title "Ads Express $VERSION" \
    --notes "Instaladores do Ads Express $VERSION. Baixe o do seu sistema: **.exe** (Windows) ou **.dmg** (Mac)." \
    || { echo "Falha ao criar a Release."; exit 1; }
else
  say "Release $TAG já existe — atualizando os arquivos…"
fi

# Sobe cada instalador (--clobber substitui se já houver um com o mesmo nome).
for a in "${ASSETS[@]}"; do
  say "Enviando: $(basename "$a")"
  gh release upload "$TAG" "$a" --repo "$REPO" --clobber || echo "  (falhou: $(basename "$a"))"
done

URL="$(gh release view "$TAG" --repo "$REPO" --json url -q .url 2>/dev/null || echo '')"
echo
echo "  Pronto! Release publicada."
[ -n "$URL" ] && echo "  Página de download: $URL"
echo "  (Repositório é PRIVADO: só quem tem acesso baixa. Pra download público, torne o"
echo "   repositório público ou use um repositório público só de releases.)"
