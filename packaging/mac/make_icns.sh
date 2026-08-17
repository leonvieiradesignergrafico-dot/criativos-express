#!/usr/bin/env bash
#
# make_icns.sh — gera packaging/icons/AdsExpress.icns a partir do iconset já pronto.
#
# O iconset (packaging/icons/AdsExpress.iconset/) já contém os 10 PNGs com os nomes
# EXATOS que o iconutil exige (icon_16x16.png, icon_16x16@2x.png, ..., icon_512x512@2x.png).
# Este script só empacota tudo num .icns. Rode-o no Mac (iconutil é uma ferramenta
# nativa do macOS, não existe no Windows).
#
# Uso:
#   bash packaging/mac/make_icns.sh
#
# Idempotente: sobrescreve o .icns anterior sem reclamar.
set -euo pipefail

# Raiz do projeto = dois níveis acima deste script (packaging/mac/ -> raiz).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

ICONSET="$ROOT/packaging/icons/AdsExpress.iconset"
OUT="$ROOT/packaging/icons/AdsExpress.icns"

echo "==> Gerando .icns"
echo "    iconset : $ICONSET"
echo "    saída   : $OUT"

if [ ! -d "$ICONSET" ]; then
  echo "ERRO: iconset não encontrado em $ICONSET" >&2
  exit 1
fi

if command -v iconutil >/dev/null 2>&1; then
  iconutil -c icns "$ICONSET" -o "$OUT"
  echo "==> OK: $OUT"
else
  echo "ERRO: 'iconutil' não encontrado — você está mesmo num Mac?" >&2
  echo >&2
  echo "FALLBACK (sem iconutil, ex.: CI Linux) — gere o .icns com Pillow a partir do" >&2
  echo "PNG 1024x1024 (packaging/icons/app-1024.png). Rode no Python do build:" >&2
  cat >&2 <<'PYFALLBACK'

    python - <<'PY'
    from PIL import Image
    from pathlib import Path
    root = Path("packaging/icons")
    img = Image.open(root / "app-1024.png").convert("RGBA")
    # Pillow escreve .icns diretamente (embute os tamanhos padrão do macOS).
    img.save(root / "AdsExpress.icns", format="ICNS")
    print("AdsExpress.icns gerado via Pillow")
    PY

PYFALLBACK
  exit 1
fi
