"""Criativos Express — app desktop.

Sobe o servidor local numa thread e abre uma janela nativa (pywebview).
Rode:  python desktop.py
"""
from __future__ import annotations

import threading
import time
from urllib.request import urlopen

import webview

from app.server import app

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}"


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
    threading.Thread(target=_run_server, daemon=True).start()
    _esperar_servidor()
    webview.create_window(
        "Criativos Express",
        URL,
        width=1240,
        height=860,
        min_size=(980, 680),
        background_color="#1e1e1e",
    )
    webview.start()


if __name__ == "__main__":
    main()
