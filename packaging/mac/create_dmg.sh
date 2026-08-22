#!/usr/bin/env bash
#
# create_dmg.sh — cria um .dmg distribuível do Ads Express.
#
# O .dmg abre mostrando o "Ads Express.app" ao lado de um atalho para a pasta
# Aplicativos — o usuário só arrasta um para o outro (instalação clássica do Mac).
#
# Usa 'create-dmg' se estiver instalado (visual bonito); senão cai no 'hdiutil'
# nativo (funciona sempre). Rode DEPOIS de build_mac.sh (e, idealmente, de
# codesign_notarize.sh, para o DMG conter o app já notarizado).
#
# Uso:
#   bash packaging/mac/create_dmg.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

APP="$ROOT/dist/Ads Express.app"
VOL_NAME="Ads Express"
VERSION="${ADSEXPRESS_VERSION:-1.0.0}"
DMG_OUT="$ROOT/Ads Express $VERSION.dmg"   # na RAIZ (igual ao instalador do Windows)

if [ ! -d "$APP" ]; then
  echo "ERRO: não achei '$APP'. Rode antes: bash packaging/mac/build_mac.sh" >&2
  exit 1
fi

rm -f "$DMG_OUT"

if command -v create-dmg >/dev/null 2>&1; then
  echo "==> Gerando DMG com create-dmg (layout bonito)"
  # DMG LIMPO: só o app + o atalho p/ /Applications (--app-drop-link). É o padrão de
  # todo Mac — arraste um no outro. Os utilitários (first_run/remove_quarantine) NÃO
  # entram aqui de propósito: eles vivem em packaging/mac/ e o instalar_tudo já roda o
  # first-run; jogá-los soltos no DMG só polui a janela de instalação.
  create-dmg \
    --volname "$VOL_NAME" \
    --window-pos 200 120 \
    --window-size 560 360 \
    --icon-size 128 \
    --icon "Ads Express.app" 150 180 \
    --app-drop-link 410 180 \
    --hdiutil-quiet \
    "$DMG_OUT" \
    "$APP"
else
  echo "==> 'create-dmg' não instalado — usando hdiutil (nativo)."
  echo "    (Para o layout bonito: brew install create-dmg)"
  STAGE="$(mktemp -d)"
  echo "==> Montando conteúdo em $STAGE"
  cp -R "$APP" "$STAGE/"
  # DMG LIMPO: só o app + atalho de arrastar-e-soltar para /Applications. Nada de
  # .command solto (ver comentário no ramo create-dmg acima).
  ln -s /Applications "$STAGE/Applications"

  echo "==> Criando $DMG_OUT"
  hdiutil create \
    -volname "$VOL_NAME" \
    -srcfolder "$STAGE" \
    -ov -format UDZO \
    "$DMG_OUT"
  rm -rf "$STAGE"
fi

echo
echo "======================================================================"
echo " OK! DMG criado:"
echo "   $DMG_OUT"
echo
echo " App é ad-hoc-assinado: na 1ª abertura, BOTÃO DIREITO no app -> Abrir."
echo " Se o DMG for BAIXADO da internet e reclamar de 'danificado', rode o utilitário"
echo " packaging/mac/remove_quarantine.command (não vai mais solto dentro do DMG)."
echo "======================================================================"
