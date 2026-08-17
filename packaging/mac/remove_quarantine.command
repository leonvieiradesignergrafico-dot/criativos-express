#!/usr/bin/env bash
#
# remove_quarantine.command — libera o Ads Express num Mac quando o app NÃO está
# assinado/notarizado (distribuição local/interna).
#
# POR QUÊ: o macOS carimba todo arquivo baixado com o atributo "com.apple.quarantine".
# Num app não assinado isso vira o bloqueio "'Ads Express' está danificado e não pode
# ser aberto" (ou "de desenvolvedor não identificado"). O app NÃO está danificado — é
# só o Gatekeeper. Este script remove esse carimbo e o app abre normalmente.
#
# COMO USAR (usuário final): dê DOIS CLIQUES neste arquivo. (Se o Terminal disser que
# não pode executar, veja o README_MAC.md — pode ser preciso liberar este .command
# também, com: xattr -d com.apple.quarantine remove_quarantine.command)
#
# Idempotente: pode rodar quantas vezes quiser.
set -uo pipefail

# Candidatos onde o app pode estar: /Applications, ~/Applications, ~/Downloads,
# a Mesa, e a mesma pasta deste .command (caso o usuário rode de dentro do DMG/pasta).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANDIDATOS=(
  "/Applications/Ads Express.app"
  "$HOME/Applications/Ads Express.app"
  "$HOME/Downloads/Ads Express.app"
  "$HOME/Desktop/Ads Express.app"
  "$HERE/Ads Express.app"
)

echo "======================================================================"
echo "  Ads Express — liberar o app (remover quarentena do macOS)"
echo "======================================================================"
echo

achou=0
for APP in "${CANDIDATOS[@]}"; do
  if [ -d "$APP" ]; then
    achou=1
    echo "  → Encontrado: $APP"
    echo "    Removendo o atributo de quarentena..."
    if xattr -dr com.apple.quarantine "$APP" 2>/dev/null; then
      echo "    OK — este app foi liberado."
    else
      echo "    (nada a remover, ou já estava liberado)"
    fi
    echo
  fi
done

if [ "$achou" -eq 0 ]; then
  echo "  Não encontrei 'Ads Express.app' nos locais usuais."
  echo "  Arraste o app para a pasta Aplicativos (/Applications) e rode este arquivo de novo,"
  echo "  OU rode manualmente no Terminal (troque o caminho):"
  echo
  echo "      xattr -dr com.apple.quarantine \"/caminho/para/Ads Express.app\""
  echo
else
  echo "  Pronto! Agora abra o 'Ads Express' normalmente (dois cliques)."
  echo "  Se AINDA aparecer aviso: clique com o botão direito no app → Abrir → Abrir."
fi

echo
echo "  (Pode fechar esta janela.)"
# Mantém a janela do Terminal aberta pra pessoa ler a mensagem (quando aberto por 2 cliques).
if [ -t 0 ]; then
  read -r -p "  Pressione ENTER para sair..." _ || true
fi
