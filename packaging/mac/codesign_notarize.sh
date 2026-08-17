#!/usr/bin/env bash
#
# codesign_notarize.sh — assina, notariza e "grampeia" (staple) o Ads Express.app.
#
# Este é o caminho PROFISSIONAL: o usuário final abre o app com dois cliques, SEM o
# aviso "app está danificado / desenvolvedor não identificado". Requer uma conta paga
# do Apple Developer Program (US$99/ano) e um certificado "Developer ID Application".
#
# PRÉ-REQUISITOS (feitos UMA vez, no Mac que builda):
#   1. Conta paga: https://developer.apple.com/programs/
#   2. No Xcode (ou developer.apple.com) crie/baixe o certificado
#      "Developer ID Application: SEU NOME (TEAMID)" e instale-o no Keychain.
#      Confira com:  security find-identity -v -p codesigning
#   3. Gere uma SENHA DE APP (app-specific password) em https://appleid.apple.com
#      (seção Segurança). É ela — não a senha real do Apple ID — que vai em APPLE_PASSWORD.
#
# VARIÁVEIS DE AMBIENTE (obrigatórias):
#   DEVELOPER_ID   = "Developer ID Application: Seu Nome (TEAMID)"
#   APPLE_ID       = seu-email@apple.com
#   TEAM_ID        = TEAMID  (10 caracteres, ex.: AB12CD34EF)
#   APPLE_PASSWORD = senha-de-app (xxxx-xxxx-xxxx-xxxx)
#
# Uso:
#   export DEVELOPER_ID="Developer ID Application: Fulano (AB12CD34EF)"
#   export APPLE_ID="fulano@icloud.com"
#   export TEAM_ID="AB12CD34EF"
#   export APPLE_PASSWORD="abcd-efgh-ijkl-mnop"
#   bash packaging/mac/codesign_notarize.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
APP="$ROOT/dist/Ads Express.app"

: "${DEVELOPER_ID:?defina DEVELOPER_ID (ex.: 'Developer ID Application: Fulano (AB12CD34EF)')}"
: "${APPLE_ID:?defina APPLE_ID (seu e-mail do Apple Developer)}"
: "${TEAM_ID:?defina TEAM_ID (10 caracteres)}"
: "${APPLE_PASSWORD:?defina APPLE_PASSWORD (senha de app, NÃO a senha do Apple ID)}"

if [ ! -d "$APP" ]; then
  echo "ERRO: não achei '$APP'. Rode antes: bash packaging/mac/build_mac.sh" >&2
  exit 1
fi

ENTITLEMENTS="$HERE/entitlements.plist"

echo "==> [1/5] Assinando 'inside-out' (hardened runtime, sem --deep) ..."
# Por que NÃO usar --deep: a Apple DESENCORAJA --deep para bundles com muitas
# dylibs (o PyInstaller gera dezenas). O --deep pode deixar código aninhado
# mal-assinado (flags/entitlements erradas em binários internos) e a notarização
# então REJEITA o app. O jeito correto é assinar "inside-out": primeiro todo
# binário Mach-O interno (.dylib, .so, frameworks, executáveis embarcados), do
# mais interno pro mais externo, e só DEPOIS o .app inteiro por último.
#
# Flags em cada assinatura (idênticas p/ todos):
#   --force            = re-assina se já houver assinatura.
#   --options runtime  = hardened runtime (exigido pela notarização).
#   --timestamp        = timestamp seguro da Apple (exigido pela notarização).
#   --entitlements ... = as permissões do hardened runtime.

# Nome do executável principal dentro de Contents/MacOS (não deve ser assinado
# aqui na varredura interna — ele é assinado junto com o .app no passo final).
MAIN_BIN="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist" 2>/dev/null || true)"
MAIN_PATH="$APP/Contents/MacOS/$MAIN_BIN"

sign_one() {
  # Assina um único binário interno com as mesmas flags (sem --deep).
  codesign --force --verbose \
    --options runtime \
    --timestamp \
    --entitlements "$ENTITLEMENTS" \
    --sign "$DEVELOPER_ID" \
    "$1"
}

# 1a) Todas as bibliotecas dinâmicas (.dylib) e módulos de extensão Python (.so).
#     -print0 + read -d '' trata corretamente nomes com espaço.
#     'sort -rz' ordena decrescente => caminhos mais profundos (internos) primeiro.
echo "    -> assinando .dylib e .so ..."
find "$APP" \( -name "*.dylib" -o -name "*.so" \) -print0 \
  | sort -rz \
  | while IFS= read -r -d '' lib; do
      sign_one "$lib"
    done

# 1b) Demais binários Mach-O embarcados (executáveis internos, frameworks, helpers)
#     em Contents/Frameworks, Contents/Resources e Contents/MacOS — EXCETO o
#     executável principal (assinado no passo final junto do bundle).
echo "    -> assinando executáveis Mach-O embarcados ..."
for dir in "$APP/Contents/Frameworks" "$APP/Contents/Resources" "$APP/Contents/MacOS"; do
  [ -d "$dir" ] || continue
  find "$dir" -type f -perm +111 -print0 \
    | sort -rz \
    | while IFS= read -r -d '' bin; do
        # pula o executável principal e o que não for Mach-O.
        [ "$bin" = "$MAIN_PATH" ] && continue
        case "$bin" in
          *.dylib|*.so) continue ;;  # já assinados no passo 1a.
        esac
        if /usr/bin/file "$bin" | grep -q 'Mach-O'; then
          sign_one "$bin"
        fi
      done
done

# 1c) Por ÚLTIMO, o .app inteiro (sem --deep). Isso assina o executável principal
#     e sela o bundle já com todo o código interno assinado.
echo "    -> assinando o bundle .app (por último) ..."
sign_one "$APP"

echo "==> [2/5] Verificando a assinatura ..."
# Na VERIFICAÇÃO --deep é ok (e desejável): percorre e confere todo o nested code.
# O que a Apple desencoraja é ASSINAR com --deep, não verificar com --deep.
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> [3/5] Zipando p/ notarização ..."
ZIP="$ROOT/dist/AdsExpress-notarize.zip"
rm -f "$ZIP"
# ditto preserva a estrutura do bundle (necessário p/ notarytool).
/usr/bin/ditto -c -k --keepParent "$APP" "$ZIP"

echo "==> [4/5] Enviando pra Apple (notarytool submit --wait) ... pode levar alguns minutos."
xcrun notarytool submit "$ZIP" \
  --apple-id "$APPLE_ID" \
  --team-id "$TEAM_ID" \
  --password "$APPLE_PASSWORD" \
  --wait

echo "==> [5/5] Grampeando o ticket (stapler staple) no .app ..."
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

rm -f "$ZIP"

echo
echo "======================================================================"
echo " OK! '$APP' está ASSINADO + NOTARIZADO + STAPLED."
echo " Agora empacote num DMG p/ distribuir:"
echo "     bash packaging/mac/create_dmg.sh"
echo " O usuário final abre com 2 cliques, SEM aviso de Gatekeeper."
echo "======================================================================"
