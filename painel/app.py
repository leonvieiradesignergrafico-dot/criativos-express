"""Painel local do Criativos Express.

Dashboard web para disparar a geração e acompanhar o progresso ao vivo
(barra de progresso + grade dos criativos aparecendo).

Rodar:  python painel/app.py   ->  http://localhost:5000
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, send_from_directory

# Permite importar gerar.py da raiz do projeto.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gerar  # noqa: E402

PRODUCTS = ROOT / "products"

app = Flask(__name__)

# Controla execuções em andamento por produto (evita disparo duplo).
_locks: dict[str, threading.Lock] = {}


def _lock(produto: str) -> threading.Lock:
    return _locks.setdefault(produto, threading.Lock())


def listar_produtos() -> list[dict]:
    itens = []
    if not PRODUCTS.exists():
        return itens
    for d in sorted(PRODUCTS.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        prompts = d / "output" / "prompts.json"
        n = 0
        if prompts.exists():
            try:
                data = json.loads(prompts.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data = data.get("criativos", [])
                n = len(data)
            except Exception:
                n = 0
        itens.append({"nome": d.name, "prompts": n})
    return itens


def ler_status(produto: str) -> dict:
    f = PRODUCTS / produto / "output" / "criativos" / "status.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"total": 0, "feitos": 0, "atual": None, "arquivos": [], "erros": [],
            "em_andamento": False}


@app.route("/")
def index():
    return render_template("index.html", produtos=listar_produtos())


@app.route("/status/<produto>")
def status(produto):
    return jsonify(ler_status(produto))


@app.route("/gerar/<produto>", methods=["POST"])
def gerar_endpoint(produto):
    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "msg": "Já existe uma geração em andamento."}), 409

    def tarefa():
        try:
            gerar.gerar_criativos(produto)
        except Exception as e:  # noqa: BLE001
            out = PRODUCTS / produto / "output" / "criativos"
            out.mkdir(parents=True, exist_ok=True)
            (out / "status.json").write_text(
                json.dumps(
                    {"total": 0, "feitos": 0, "atual": None, "arquivos": [],
                     "erros": [{"id": "-", "erro": str(e)}], "em_andamento": False},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            lock.release()

    threading.Thread(target=tarefa, daemon=True).start()
    return jsonify({"ok": True, "msg": "Geração iniciada."})


@app.route("/criativos/<produto>/<path:arquivo>")
def criativo(produto, arquivo):
    pasta = PRODUCTS / produto / "output" / "criativos"
    if not (pasta / arquivo).exists():
        abort(404)
    return send_from_directory(pasta, arquivo)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
