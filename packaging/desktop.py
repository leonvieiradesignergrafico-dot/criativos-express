"""Criativos Express — app desktop.

Sobe o servidor local numa thread e abre uma janela nativa (pywebview).
Rode:  python desktop.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import webview

from app.server import app

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}"


def _checar_setup_primeira_vez() -> None:
    """No app empacotado: se as CLIs essenciais faltam, abre o 'Setup Ads Express'.

    Só age quando congelado (o dev que roda `python desktop.py` já tem tudo). Não
    bloqueia: apenas dispara o assistente ao lado do .exe, se existir."""
    if not getattr(sys, "frozen", False):
        return
    if all(shutil.which(x) for x in ("node", "claude", "codex")):
        return
    base = Path(sys.executable).resolve().parent
    for setup in (base / "setup" / "Setup Ads Express.exe",
                  base / "Setup Ads Express.exe"):
        if setup.exists():
            try:
                subprocess.Popen([str(setup)],
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            except OSError:
                pass
            return


def _run_server():
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)


def _esperar_servidor(timeout=15):
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            urlopen(URL + "/api/produtos", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    _checar_setup_primeira_vez()
    threading.Thread(target=_run_server, daemon=True).start()
    _esperar_servidor()
    webview.create_window(
        "Ads Express",
        URL,
        width=1240,
        height=860,
        min_size=(980, 680),
        background_color="#1e1e1e",
    )
    webview.start()


if __name__ == "__main__":
    main()
