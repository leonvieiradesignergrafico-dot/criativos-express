"""Deploy local — cria um atalho de duplo-clique (sem terminal) para o app.

O app roda com o Python que você já tem: o atalho aponta para `pythonw.exe`
(sem janela de console) executando `desktop.py`, que sobe o servidor local e abre
a janela nativa. Os seus dados (`products/`, `config.toml`) continuam onde estão.

Uso:
    python deploy_local/criar_atalho.py

Cria:
  - deploy_local/icone.ico            (ícone do app)
  - "Criativos Express.lnk" na sua Área de Trabalho
  - "Criativos Express.lnk" na raiz do projeto (backup/atalho local)

Rode de novo se mover a pasta do projeto ou trocar de Python.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DESKTOP_PY = PROJ / "desktop.py"
ICON = Path(__file__).resolve().parent / "icone-v3.ico"
ICON_SOURCE = Path(__file__).resolve().parent / "icone-v3.png"
NOME = "Criativos Express"


def _pythonw() -> Path:
    """pythonw.exe do MESMO Python que está rodando este script (sem console)."""
    cand = Path(sys.prefix) / "pythonw.exe"
    if cand.exists():
        return cand
    # Fallback: ao lado do python.exe atual.
    alt = Path(sys.executable).with_name("pythonw.exe")
    return alt if alt.exists() else Path(sys.executable)


def gerar_icone() -> None:
    """Ícone grafite (estilo Apple) com uma marca de 'imagem/criativo' em branco."""
    from PIL import Image, ImageDraw
    # Fonte rasterizada literalmente a partir do SVG usado no cabeÃ§alho.
    if ICON_SOURCE.exists():
        base = Image.open(ICON_SOURCE).convert("RGBA")
        # No Explorer, transparência nos cantos revela o fundo branco da janela.
        # Preenchemos os cantos com o mesmo grafite do fundo para o ícone não
        # ganhar uma moldura branca, mantendo a aparência escura na taskbar.
        mascara = Image.new("L", base.size, 0)
        ImageDraw.Draw(mascara).rounded_rectangle(
            [0, 0, base.width - 1, base.height - 1], radius=76, fill=255)
        base.putalpha(mascara)
        fundo = Image.new("RGBA", base.size, (48, 48, 50, 255))
        fundo.alpha_composite(base)
        base = fundo
        base.save(
            ICON, format="ICO",
            sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
        print(f"  [ok] icone: {ICON}")
        return

    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Fundo: quadrado arredondado grafite (mesmo tom do background do app).
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=56, fill=(30, 30, 32, 255))

    # Moldura de foto (retângulo arredondado, contorno branco).
    branco = (245, 245, 247, 255)
    cinza = (210, 210, 214, 255)
    d.line([(192, 234), (43, 234), (22, 213), (22, 64)], fill=branco, width=10, joint="curve")
    d.rounded_rectangle([64, 22, 234, 192], radius=22, outline=branco, width=10)
    # Sol (círculo).
    d.ellipse([160, 64, 202, 106], fill=branco)
    # Montanha (dois triângulos), recortada visualmente pela moldura.
    d.polygon([(82, 178), (126, 116), (174, 178)], fill=branco)
    d.polygon([(132, 178), (166, 132), (213, 178)], fill=cinza)

    tamanhos = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(ICON, format="ICO", sizes=tamanhos)
    print(f"  [ok] icone: {ICON}")


def criar_atalho(destino: Path) -> None:
    """Cria um .lnk em `destino` apontando pythonw -> desktop.py (workdir = projeto)."""
    pythonw = _pythonw()
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{destino}'); "
        f"$s.TargetPath = '{pythonw}'; "
        f"$s.Arguments = '\"{DESKTOP_PY}\"'; "
        f"$s.WorkingDirectory = '{PROJ}'; "
        f"$s.IconLocation = '{ICON}'; "
        "$s.Description = 'Impressora de Criativos'; "
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   capture_output=True)
    print(f"  [ok] atalho: {destino}")


def area_de_trabalho() -> Path:
    """Área de Trabalho real do usuário (respeita pastas redirecionadas, ex.: D:\\Desktop)."""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True)
    p = (r.stdout or "").strip()
    return Path(p) if p else Path.home() / "Desktop"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # evita UnicodeEncodeError no console cp1252
    except Exception:
        pass
    if os.name != "nt":
        print("Este empacotamento é para Windows.")
        return 1
    if not DESKTOP_PY.exists():
        print(f"Não encontrei {DESKTOP_PY}")
        return 1

    print("Empacotando (deploy local)...")
    gerar_icone()
    criar_atalho(area_de_trabalho() / f"{NOME}.lnk")
    criar_atalho(PROJ / f"{NOME}.lnk")
    print("\nPronto. Dê duplo-clique em \"Criativos Express\" na Área de Trabalho.")
    print("Dica: botao direito no atalho -> Fixar na barra de tarefas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
