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
DMG_OUT="$ROOT/dist/Ads Express $VERSION.dmg"

if [ ! -d "$APP" ]; then
  echo "ERRO: não achei '$APP'. Rode antes: bash packaging/mac/build_mac.sh" >&2
  exit 1
fi

rm -f "$DMG_OUT"

if command -v create-dmg >/dev/null 2>&1; then
  echo "==> Gerando DMG com create-dmg (layout bonito)"
  # create-dmg já adiciona o link p/ /Applications via --app-drop-link.
  # Embute os utilitarios de primeira execucao / quarentena no DMG (mesmo conteudo
  # do fallback hdiutil abaixo), para app distribuido SEM assinatura.
  create-dmg \
    --volname "$VOL_NAME" \
    --window-pos 200 120 \
    --window-size 640 420 \
    --icon-size 128 \
    --icon "Ads Express.app" 160 190 \
    --app-drop-link 480 190 \
    --add-file "remove_quarantine.command" "$HERE/remove_quarantine.command" 160 330 \
    --add-file "first_run_mac.command" "$HERE/first_run_mac.command" 480 330 \
    --hdiutil-quiet \
    "$DMG_OUT" \
    "$APP"
else
  echo "==> 'create-dmg' não instalado — usando hdiutil (nativo)."
  echo "    (Para o layout bonito: brew install create-dmg)"
  STAGE="$(mktemp -d)"
  echo "==> Montando conteúdo em $STAGE"
  cp -R "$APP" "$STAGE/"
  # Atalho de arrastar-e-soltar para /Applications.
  ln -s /Applications "$STAGE/Applications"
  # Inclui os utilitários de quarentena e first-run no DMG (app distribuído SEM assinatura).
  cp "$HERE/remove_quarantine.command" "$STAGE/" 2>/dev/null || true
  cp "$HERE/first_run_mac.command" "$STAGE/" 2>/dev/null || true
  chmod +x "$STAGE/remove_quarantine.command" "$STAGE/first_run_mac.command" 2>/dev/null || true

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
echo " Se o app NÃO for assinado/notarizado, avise o usuário para rodar o"
echo " 'remove_quarantine.command' (incluído no DMG) após arrastar para Aplicativos."
echo "======================================================================"
