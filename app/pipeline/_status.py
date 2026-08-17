"""Status de job por vídeo (status.json + heartbeat), padrão herdado do app irmão.

O front faz polling de /api/status a cada 1,5s; o heartbeat regrava o arquivo a
cada ~15s para o app distinguir "gerando há minutos" de "processo morto".
"""
from __future__ import annotations

import threading
import time
import uuid

from workspace import atomic_write_json, ler_json


class JobStatus:
    def __init__(self, status_file, etapa: str, total: int):
        self.file = status_file
        self._lock = threading.Lock()
        self._hb_stop = threading.Event()
        self.dado = {
            "id": uuid.uuid4().hex,
            "etapa": etapa,
            "total": total,
            "feitos": 0,
            "atuais": [],
            "erros": [],
            "em_andamento": True,
            "cancelado": False,
            "inicio": time.time(),
            "atualizado": time.time(),
        }
        self.salvar()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    @staticmethod
    def em_andamento(status_file) -> bool:
        """True se OUTRA execução está viva (batimento há menos de 60s)."""
        s = ler_json(status_file) or {}
        return bool(s.get("em_andamento")) and (time.time() - float(s.get("atualizado") or 0)) < 60

    def salvar(self):
        self.dado["atualizado"] = time.time()
        atomic_write_json(self.file, dict(self.dado))

    def _heartbeat(self):
        while not self._hb_stop.wait(15):
            with self._lock:
                if not self.dado.get("em_andamento"):
                    break
                self.salvar()

    def etapa(self, etapa: str, total: int | None = None):
        with self._lock:
            self.dado["etapa"] = etapa
            if total is not None:
                self.dado["total"] = total
                self.dado["feitos"] = 0
            self.dado["atuais"] = []
            self.salvar()

    def comecou(self, item: str):
        with self._lock:
            self.dado["atuais"].append(item)
            self.salvar()

    def terminou(self, item: str, erro: str | None = None):
        with self._lock:
            if item in self.dado["atuais"]:
                self.dado["atuais"].remove(item)
            self.dado["feitos"] += 1
            if erro:
                self.dado["erros"].append({"item": item, "erro": erro})
            self.salvar()

    def fim(self, cancelado: bool = False):
        self._hb_stop.set()
        with self._lock:
            self.dado["em_andamento"] = False
            self.dado["cancelado"] = cancelado
            self.dado["atuais"] = []
            self.salvar()
