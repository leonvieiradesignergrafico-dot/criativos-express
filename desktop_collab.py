"""Criativos Collab Store — mesma ferramenta, skin premium claro (cliente).

MESMA lógica/servidor do app padrão (app.server); só muda o VISUAL (marca "collab").
O desktop.py original continua abrindo o visual atual, intacto. Rode este por um
atalho separado ("Criativos Collab Store") para a demo do cliente.

Roda numa porta diferente (5001) para poder abrir junto do app padrão (5000).
Rode:  python desktop_collab.py
"""
from __future__ import annotations

import os
import threading
import time
from urllib.request import urlopen

# A marca é lida pelo servidor via env (e reforçada por ?brand= na URL).
os.environ.setdefault("CRIATIVOS_BRAND", "collab")

import webview  # noqa: E402

from app.server import app  # noqa: E402

HOST = "127.0.0.1"
PORT = 5001
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
        "Criativos Collab Store",
        URL + "/?brand=collab",
        width=1240,
        height=860,
        min_size=(980, 680),
        background_color="#f6f9fc",
    )
    webview.start()


if __name__ == "__main__":
    main()
