#!/usr/bin/env bash
#
# Instalar no Mac.command — ATALHO na cara da pasta (raiz do projeto).
#
# É só dar DOIS CLIQUES neste arquivo. Ele não faz nada sozinho: apenas chama o
# instalador de verdade, que mora em packaging/mac/instalar_tudo.command (junto com
# os outros scripts de build, pra não bagunçar a raiz). Assim o usuário de Mac acha
# o instalador logo ao abrir a pasta — igual o .exe do Windows fica na raiz.
#
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL="$HERE/packaging/mac/instalar_tudo.command"

if [ ! -f "$REAL" ]; then
  printf "\n  Não encontrei o instalador em:\n    %s\n\n" "$REAL"
  printf "  Confira se a pasta do projeto veio completa (com a pasta packaging/).\n\n"
  if [ -t 0 ]; then read -r -p "  Pressione ENTER para sair..." _ || true; fi
  exit 1
fi

# exec = substitui este processo pelo instalador real, então a pausa "Pressione ENTER
# para sair" do próprio instalador continua funcionando normalmente no fim.
exec bash "$REAL"
