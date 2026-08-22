#!/usr/bin/env bash
#
# create_dmg.sh — cria um .dmg distribuível do Ads Express.
#
# O .dmg entrega o INSTALADOR PREMIUM: abre mostrando o "Ads Express Installer.app",
# o usuário dá dois cliques e o wizard faz tudo (copia o app pra Aplicativos, instala
# Node/CLIs, logins). Se o instalador não tiver sido buildado, cai no modo antigo
# (app + atalho de Aplicativos pra arrastar).
#
# Usa 'create-dmg' se estiver instalado (visual bonito); senão cai no 'hdiutil' nativo.
# Rode DEPOIS de build_mac.sh.
#
# Uso:
#   bash packaging/mac/create_dmg.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

INSTALLER="$ROOT/dist/Ads Express Installer.app"
APP="$ROOT/dist/Ads Express.app"
VOL_NAME="Ads Express"
VERSION="${ADSEXPRESS_VERSION:-1.0.0}"
DMG_OUT="$ROOT/Ads Express $VERSION.dmg"   # na RAIZ (igual ao instalador do Windows)

rm -f "$DMG_OUT"

if [ -d "$INSTALLER" ]; then
  # ---- Modo preferido: entrega o INSTALADOR premium (dois cliques → wizard) ----
  PAYLOAD="$INSTALLER"; PAYLOAD_NAME="Ads Express Installer.app"; MODO="instalador"
elif [ -d "$APP" ]; then
  # ---- Fallback: entrega o app pra arrastar pra Aplicativos ----
  PAYLOAD="$APP"; PAYLOAD_NAME="Ads Express.app"; MODO="arrastar"
else
  echo "ERRO: não achei nem o instalador nem o app em dist/. Rode: bash packaging/mac/build_mac.sh" >&2
  exit 1
fi
echo "==> Empacotando ($MODO): $PAYLOAD_NAME"

if command -v create-dmg >/dev/null 2>&1; then
  echo "==> Gerando DMG com create-dmg (layout bonito)"
  if [ "$MODO" = "instalador" ]; then
    # Só o instalador, centralizado. Sem atalho de Aplicativos: o wizard cuida da cópia.
    create-dmg \
      --volname "$VOL_NAME" \
      --window-pos 200 120 \
      --window-size 500 340 \
      --icon-size 128 \
      --icon "$PAYLOAD_NAME" 250 160 \
      --hdiutil-quiet \
      "$DMG_OUT" \
      "$PAYLOAD"
  else
    create-dmg \
      --volname "$VOL_NAME" \
      --window-pos 200 120 \
      --window-size 560 360 \
      --icon-size 128 \
      --icon "$PAYLOAD_NAME" 150 180 \
      --app-drop-link 410 180 \
      --hdiutil-quiet \
      "$DMG_OUT" \
      "$PAYLOAD"
  fi
else
  echo "==> 'create-dmg' não instalado — usando hdiutil (nativo)."
  echo "    (Para o layout bonito: brew install create-dmg)"
  STAGE="$(mktemp -d)"
  echo "==> Montando conteúdo em $STAGE"
  cp -R "$PAYLOAD" "$STAGE/"
  # No modo "arrastar" adiciona o atalho de Aplicativos; no modo instalador, não precisa.
  [ "$MODO" = "arrastar" ] && ln -s /Applications "$STAGE/Applications"

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
if [ "$MODO" = "instalador" ]; then
  echo " Conteúdo: Ads Express Installer.app (dois cliques → instalação premium)."
  echo " App/instalador são ad-hoc-assinados: na 1ª abertura, BOTÃO DIREITO -> Abrir."
else
  echo " Conteúdo: Ads Express.app (arraste pra Aplicativos). 1ª abertura: botão-direito -> Abrir."
fi
echo " Se o DMG for BAIXADO da internet e reclamar de 'danificado', rode:"
echo "   packaging/mac/remove_quarantine.command"
echo "======================================================================"
