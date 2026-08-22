"""Console de diagnóstico embutido.

Captura logs do Python, exceções não tratadas e o stderr num buffer circular que o app
exibe numa tela `/console`. Serve pra depurar SEM terminal (essencial no Mac, onde o
.app windowed engole o stderr). Zero dependência de outros módulos do app (importável
por claude_bridge/ugc_web sem ciclo)."""
from __future__ import annotations

import logging
import sys
import time
import traceback
from collections import deque
from threading import Lock

_BUF: deque = deque(maxlen=1000)
_LOCK = Lock()


def registrar(nivel: str, texto: str) -> None:
    """Adiciona uma linha ao buffer (thread-safe)."""
    if not texto:
        return
    with _LOCK:
        _BUF.append({"t": time.time(), "nivel": str(nivel), "texto": str(texto)})


def linhas() -> list:
    with _LOCK:
        return list(_BUF)


def limpar() -> None:
    with _LOCK:
        _BUF.clear()


class _BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            registrar(record.levelname, self.format(record))
        except Exception:  # noqa: BLE001 — logging jamais pode quebrar o app
            pass


class _StderrTee:
    """Espelha o stderr no buffer, preservando o destino original (se houver)."""

    def __init__(self, orig):
        self._orig = orig
        self._parcial = ""

    def write(self, s):
        try:
            if self._orig is not None:
                self._orig.write(s)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._parcial += s
            while "\n" in self._parcial:
                linha, self._parcial = self._parcial.split("\n", 1)
                if linha.strip():
                    registrar("STDERR", linha)
        except Exception:  # noqa: BLE001
            pass

    def flush(self):
        try:
            if self._orig is not None:
                self._orig.flush()
        except Exception:  # noqa: BLE001
            pass


_INSTALADO = False


def instalar(app=None) -> None:
    """Liga a captura (idempotente). Chamar uma vez, após criar o app Flask."""
    global _INSTALADO
    if not _INSTALADO:
        h = _BufferHandler()
        h.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(h)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        try:
            sys.stderr = _StderrTee(sys.stderr)
        except Exception:  # noqa: BLE001
            pass

        _orig_hook = sys.excepthook

        def _excepthook(exc_type, exc, tb):
            registrar("ERRO", "".join(traceback.format_exception(exc_type, exc, tb)))
            try:
                _orig_hook(exc_type, exc, tb)
            except Exception:  # noqa: BLE001
                pass

        sys.excepthook = _excepthook
        _INSTALADO = True

    if app is not None:
        @app.errorhandler(Exception)
        def _capturar_flask(e):  # noqa: ANN001
            registrar("ERRO", "Exceção não tratada numa rota:\n" + "".join(
                traceback.format_exception(type(e), e, e.__traceback__)))
            from flask import jsonify
            return jsonify({"ok": False, "erro": str(e)}), 500
