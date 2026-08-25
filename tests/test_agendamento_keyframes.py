"""Testa o agendamento por dependência dos keyframes (_rodar_por_dependencia).

O que este teste protege (regressão real): antes existia uma BARREIRA entre duas ondas —
nenhuma cena dependente começava enquanto a onda inteira de âncoras não terminasse. Num
lote real, 4 cenas ficaram prontas em 2min06 e a onda 2 só começou 2min10 depois, por
causa de UMA cena lenta, com 4 workers ociosos.

Roda com: python tests/test_agendamento_keyframes.py
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.keyframes import _rodar_por_dependencia  # noqa: E402

FALHAS = []


def checar(cond, msg):
    print(("  ok   " if cond else "  FALHA") + f" {msg}")
    if not cond:
        FALHAS.append(msg)


def test_dependente_espera_so_a_sua_ancora():
    """Cena 2 depende da âncora 1 (lenta). Cena 3 é independente e NÃO pode esperar."""
    cenas = [{"n": 1}, {"n": 2}, {"n": 3}]
    dep = {2: 1}
    fim = {}

    def ancora_de(c):
        anc = dep.get(c["n"])
        return ("c", anc) if anc else None

    def job(c):
        time.sleep(0.6 if c["n"] == 1 else 0.05)
        fim[c["n"]] = time.perf_counter()

    t0 = time.perf_counter()
    _rodar_por_dependencia(cenas, ancora_de, job, workers=3)
    checar(set(fim) == {1, 2, 3}, "todas as cenas rodaram")
    checar(fim[2] > fim[1], "a dependente (2) so terminou depois da ancora (1)")
    checar(fim[3] - t0 < 0.5,
           f"a independente (3) NAO esperou a ancora lenta ({fim[3] - t0:.2f}s)")


def test_sem_deadlock_com_muitos_dependentes():
    """Mais dependentes que workers: as âncoras têm que pegar slot primeiro."""
    cenas = [{"n": 1}] + [{"n": i} for i in range(2, 10)]
    dep = {i: 1 for i in range(2, 10)}
    fim = {}

    def ancora_de(c):
        anc = dep.get(c["n"])
        return ("c", anc) if anc else None

    def job(c):
        time.sleep(0.05)
        fim[c["n"]] = time.perf_counter()

    pronto = threading.Event()

    def rodar():
        _rodar_por_dependencia(cenas, ancora_de, job, workers=2)
        pronto.set()

    threading.Thread(target=rodar, daemon=True).start()
    checar(pronto.wait(10), "terminou sem deadlock (2 workers, 8 dependentes)")
    checar(len(fim) == 9, f"todas as 9 cenas rodaram (rodaram {len(fim)})")
    if len(fim) == 9:
        checar(all(fim[i] > fim[1] for i in range(2, 10)),
               "toda dependente terminou depois da ancora")


def test_ancora_que_falha_nao_prende_dependente():
    """Se a âncora explode, a dependente gera assim mesmo (sem a referência) em vez de
    ficar presa pra sempre esperando um evento que nunca vem."""
    cenas = [{"n": 1}, {"n": 2}]
    fim = {}

    def ancora_de(c):
        return ("c", 1) if c["n"] == 2 else None

    def job(c):
        if c["n"] == 1:
            raise RuntimeError("ancora falhou de proposito")
        fim[c["n"]] = True

    pronto = threading.Event()
    erro = []

    def rodar():
        try:
            _rodar_por_dependencia(cenas, ancora_de, job, workers=2)
        except Exception as e:  # noqa: BLE001
            erro.append(e)
        pronto.set()

    threading.Thread(target=rodar, daemon=True).start()
    checar(pronto.wait(5), "nao ficou preso quando a ancora falhou")
    checar(fim.get(2) is True, "a dependente rodou mesmo com a ancora quebrada")


def test_cancelamento_solta_quem_espera():
    cenas = [{"n": 1}, {"n": 2}]
    cancel = threading.Event()

    def ancora_de(c):
        return ("c", 1) if c["n"] == 2 else None

    def job(c):
        if c["n"] == 1:
            while not cancel.is_set():
                time.sleep(0.05)

    pronto = threading.Event()
    threading.Thread(
        target=lambda: (_rodar_por_dependencia(cenas, ancora_de, job, workers=2, cancel_event=cancel),
                        pronto.set()), daemon=True).start()
    time.sleep(0.2)
    cancel.set()
    checar(pronto.wait(5), "o cancelamento soltou quem estava esperando a ancora")


if __name__ == "__main__":
    print("== agendamento de keyframes por dependencia ==")
    for t in (test_dependente_espera_so_a_sua_ancora,
              test_sem_deadlock_com_muitos_dependentes,
              test_ancora_que_falha_nao_prende_dependente,
              test_cancelamento_solta_quem_espera):
        print(f"\n{t.__name__}:")
        t()
    print("\n" + ("FALHAS: " + "; ".join(FALHAS) if FALHAS else "tudo passou"))
    sys.exit(1 if FALHAS else 0)
