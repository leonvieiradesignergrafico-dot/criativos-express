"""Impede a máquina de dormir enquanto há job rodando — e denuncia quando ela dormiu.

POR QUE: o app delega o trabalho pesado a processos externos (claude/codex/gcloud) que
levam minutos. Se o Mac suspende no meio, o processo é congelado e a resposta volta
quebrada — no log do usuário isso apareceu como:

    RuntimeError: API Error: Your computer went to sleep mid-response.

e, nos keyframes, como uma geração que simplesmente parava de progredir sem erro nenhum
(os processos ficam suspensos até o timeout de 600s estourar depois do wake).

COMO: enquanto existir pelo menos um job ativo, seguramos uma trava de energia do SO —
`caffeinate` no macOS, `SetThreadExecutionState` no Windows. Contagem por referência: o
primeiro job liga, o último desliga. É best-effort: se falhar, o job roda igual (só volta
a ficar exposto ao sono).

LIMITE HONESTO: nada disso impede o sono ao FECHAR A TAMPA do MacBook (clamshell). Fechou,
dorme — e aí o vigia abaixo pelo menos registra no console o que aconteceu.
"""
from __future__ import annotations

import functools
import subprocess
import sys
import threading
import time

from app import console_log

_lock = threading.Lock()
_ativos = 0
_proc = None                 # processo caffeinate (macOS)
_keeper_parar = None         # Event que solta a trava do Windows


def _ligar_macos() -> None:
    """caffeinate: -i idle sleep, -m disco, -s sistema (só vale na tomada). Fica vivo
    enquanto o processo existir; matamos ele quando o último job termina."""
    global _proc
    try:
        _proc = subprocess.Popen(
            ["/usr/bin/caffeinate", "-i", "-m", "-s"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console_log.registrar("INFO", "Energia: caffeinate ligado (a maquina nao dorme enquanto gera).")
    except Exception as e:  # noqa: BLE001
        console_log.registrar("AVISO", f"Energia: nao consegui ligar o caffeinate ({e}).")


def _desligar_macos() -> None:
    global _proc
    if _proc is None:
        return
    try:
        _proc.terminate()
    except Exception:  # noqa: BLE001
        pass
    _proc = None


def _ligar_windows() -> None:
    """ES_CONTINUOUS é por THREAD: quem chama tem que continuar viva segurando a trava.
    Por isso a trava mora numa thread dedicada que só sai quando mandamos."""
    global _keeper_parar
    _keeper_parar = threading.Event()
    parar = _keeper_parar

    def _keeper():
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_AWAYMODE_REQUIRED = 0x00000040
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)
            parar.wait()
        except Exception as e:  # noqa: BLE001
            console_log.registrar("AVISO", f"Energia: trava do Windows falhou ({e}).")
        finally:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_keeper, daemon=True, name="nosleep-keeper").start()
    console_log.registrar("INFO", "Energia: trava de suspensao ligada (Windows).")


def _desligar_windows() -> None:
    global _keeper_parar
    if _keeper_parar is not None:
        _keeper_parar.set()
        _keeper_parar = None


def adquirir() -> None:
    global _ativos
    with _lock:
        _ativos += 1
        if _ativos > 1:
            return
        if sys.platform == "darwin":
            _ligar_macos()
        elif sys.platform == "win32":
            _ligar_windows()


def liberar() -> None:
    global _ativos
    with _lock:
        _ativos = max(0, _ativos - 1)
        if _ativos:
            return
        if sys.platform == "darwin":
            _desligar_macos()
        elif sys.platform == "win32":
            _desligar_windows()


def envolver(fn):
    """Embrulha o alvo de uma thread de job: segura a trava de energia enquanto ele roda."""
    @functools.wraps(fn)
    def _wrap(*a, **kw):
        adquirir()
        try:
            return fn(*a, **kw)
        finally:
            liberar()
    return _wrap


# --- Vigia de sono ------------------------------------------------------------------
# time.monotonic() NÃO anda enquanto a máquina dorme; time.time() anda. A diferença entre
# os dois entre duas amostras é exatamente quanto tempo a máquina passou suspensa. Sem
# isto, um job que morreu por causa do sono aparece como "travou do nada".
_INTERVALO_S = 5.0
_TOLERANCIA_S = 30.0


def _vigia() -> None:
    ultimo_mono = time.monotonic()
    ultimo_wall = time.time()
    while True:
        time.sleep(_INTERVALO_S)
        mono, wall = time.monotonic(), time.time()
        dormiu = (wall - ultimo_wall) - (mono - ultimo_mono)
        if dormiu > _TOLERANCIA_S:
            minutos = dormiu / 60.0
            with _lock:
                havia_job = _ativos > 0
            msg = (f"A maquina DORMIU por ~{minutos:.0f} min. "
                   + ("Havia geracao em andamento: processos externos (claude/codex) podem "
                      "ter sido suspensos e voltado com erro ou travados ate o timeout."
                      if havia_job else "Nao havia job rodando."))
            console_log.registrar("AVISO", msg)
        ultimo_mono, ultimo_wall = mono, wall


def iniciar_vigia() -> None:
    threading.Thread(target=_vigia, daemon=True, name="nosleep-vigia").start()
