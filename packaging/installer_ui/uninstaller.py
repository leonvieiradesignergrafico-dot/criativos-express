"""Desinstalador do Ads Express (uninstall.exe, registrado em Adicionar/Remover).

Vive dentro da pasta de instalação. Como não dá pra apagar a própria pasta enquanto
roda, ele se copia pro %TEMP% e re-executa de lá com --do <pasta>, aí remove atalhos,
a chave de registro e a pasta inteira. Sem dependências (só stdlib + MessageBox nativo).
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

APP_NAME = "Ads Express"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AdsExpress"
MB_YESNO, MB_ICONQUESTION, MB_ICONINFO, IDYES = 0x4, 0x20, 0x40, 6
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _msg(texto, titulo, flags):
    return ctypes.windll.user32.MessageBoxW(0, texto, titulo, flags)


def _lnks():
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    userprofile = os.environ.get("USERPROFILE") or str(Path.home())
    return [
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk",
        Path(userprofile) / "Desktop" / f"{APP_NAME}.lnk",
    ]


def _remover_tudo(dest: Path):
    for lnk in _lnks():
        try:
            lnk.unlink()
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    shutil.rmtree(dest, ignore_errors=True)


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--do":
        time.sleep(0.8)  # deixa a instância original fechar
        _remover_tudo(Path(args[1]))
        _msg("O Ads Express foi removido do seu computador.", APP_NAME, MB_ICONINFO)
        return

    if _msg("Deseja remover o Ads Express do seu computador?",
            f"Desinstalar {APP_NAME}", MB_YESNO | MB_ICONQUESTION) != IDYES:
        return
    dest = Path(sys.executable).resolve().parent  # uninstall.exe está dentro da pasta do app
    tmp = Path(tempfile.gettempdir()) / "adsexpress_uninstall.exe"
    try:
        shutil.copy2(sys.executable, tmp)
        subprocess.Popen([str(tmp), "--do", str(dest)], creationflags=_NO_WINDOW)
    except OSError as e:
        _msg(f"Não consegui desinstalar: {e}", APP_NAME, MB_ICONINFO)


if __name__ == "__main__":
    main()
