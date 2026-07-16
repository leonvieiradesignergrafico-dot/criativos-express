"""Servidor local do Criativos Express (backend do app desktop).

Expõe uma API que o front consome via fetch. Toda a inteligência usa `claude -p`
(plano Claude) e a geração de imagem usa o Codex (plano ChatGPT). Custo de API = zero.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gerar  # noqa: E402
from app import claude_bridge  # noqa: E402

PRODUCTS = ROOT / "products"

app = Flask(__name__)

_locks: dict[str, threading.Lock] = {}


def _lock(produto: str) -> threading.Lock:
    return _locks.setdefault(produto, threading.Lock())


# ---------------------------------------------------------------- contexto ----

def montar_contexto_produto(produto: str) -> str:
    """Junta config.md + arquivos de texto de contexto/ num bloco de contexto."""
    pdir = PRODUCTS / produto
    partes = []
    cfg = pdir / "config.md"
    if cfg.exists():
        partes.append("## CONFIG DO PRODUTO\n" + cfg.read_text(encoding="utf-8", errors="replace"))
    ctx_dir = pdir / "contexto"
    if ctx_dir.exists():
        for f in sorted(ctx_dir.iterdir()):
            if f.suffix.lower() in {".md", ".txt"} and f.name != ".gitkeep":
                partes.append(f"## CONTEXTO: {f.name}\n"
                              + f.read_text(encoding="utf-8", errors="replace")[:12000])
    return "\n\n".join(partes) if partes else "(sem config/contexto preenchidos)"


SYSTEM_COPY = ("Você é um copywriter sênior de resposta direta (direct response) de altíssima "
               "conversão. Responda SEMPRE direto, usando o contexto do produto já fornecido na "
               "conversa — nunca peça briefing genérico nem mencione ferramentas, skills ou "
               "comandos do sistema. Sua função é só copy.")

SYSTEM_PROMPTS_IMG = ("Você gera prompts de imagem para criativos de anúncio. Responda SOMENTE "
                      "com o JSON pedido, sem nenhum texto fora dele.")

PREAMBULO_COPY = """Você é um copywriter sênior de resposta direta (direct response) de altíssima conversão.
Vamos trabalhar as copies de um produto específico, cujo contexto está abaixo.

Fluxo que você deve seguir na conversa:
1. A partir do pedido do usuário, PROPONHA quantas copies gerar e quantos ângulos, listando as
   ideias de ângulos (nome + 1 linha). PERGUNTE para o usuário confirmar/ajustar os ângulos.
2. Só depois de confirmado, gere as copies (headline, corpo, CTA) por ângulo.
3. Permita ajustes; itere até o usuário aprovar.
Respeite SEMPRE as regras, tom, oferta e proibições do config. Nunca prometa o que o produto não entrega.
Seja conversacional e objetivo. Quando o usuário aprovar, diga que ele pode clicar em "Salvar copies".

===== CONTEXTO DO PRODUTO =====
{contexto}
===============================

Mensagem do usuário: {mensagem}"""


# ------------------------------------------------------------------ rotas -----

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/produtos")
def produtos():
    itens = []
    if PRODUCTS.exists():
        for d in sorted(PRODUCTS.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            out = d / "output"
            itens.append({
                "nome": d.name,
                "tem_copies": (out / "copies.md").exists(),
                "tem_prompts": (out / "prompts.json").exists(),
                "tem_referencia": any(
                    (d / "referencia").glob("*")) if (d / "referencia").exists() else False,
            })
    return jsonify(itens)


@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True)
    produto = body["produto"]
    mensagem = body.get("mensagem", "")
    session_id = body.get("session_id")
    modelo = body.get("modelo") or "sonnet"

    if session_id:
        texto = mensagem
    else:
        texto = PREAMBULO_COPY.format(
            contexto=montar_contexto_produto(produto), mensagem=mensagem)

    try:
        res = claude_bridge.conversar(
            texto, session_id=session_id, modelo=modelo,
            system_prompt=SYSTEM_COPY, timeout=420)
        return jsonify({"ok": True, **res})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/copies/<produto>", methods=["GET"])
def get_copies(produto):
    f = PRODUCTS / produto / "output" / "copies.md"
    return jsonify({"conteudo": f.read_text(encoding="utf-8") if f.exists() else ""})


@app.route("/api/copies/<produto>", methods=["POST"])
def salvar_copies(produto):
    body = request.get_json(force=True)
    out = PRODUCTS / produto / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "copies.md").write_text(body.get("conteudo", ""), encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/gerar_prompts/<produto>", methods=["POST"])
def gerar_prompts(produto):
    body = request.get_json(silent=True) or {}
    modelo = body.get("modelo") or "sonnet"
    copies_f = PRODUCTS / produto / "output" / "copies.md"
    if not copies_f.exists():
        return jsonify({"ok": False, "erro": "Aprove as copies primeiro."}), 400

    contexto = montar_contexto_produto(produto)
    copies = copies_f.read_text(encoding="utf-8")
    prompt = f"""Com base nas COPIES aprovadas e no CONTEXTO do produto, gere os prompts de imagem
dos criativos. Para CADA copy, crie 1 criativo com uma cena visual coerente com a copy
(descreva ângulo de câmera, iluminação, fundo e ambientação). NÃO repita a regra de fidelidade
ao produto (o sistema injeta isso). Não invente rótulos/textos diferentes do produto real.

Responda SOMENTE com um array JSON válido, sem texto fora dele, no formato:
[{{"id":"criativo_01","angulo":"...","copy":"<headline curta>","tamanho":"1024x1024","prompt":"<cena visual detalhada>"}}]

===== CONTEXTO =====
{contexto}
===== COPIES =====
{copies}"""

    try:
        texto = claude_bridge.pedir_texto(prompt, modelo=modelo,
                                          system_prompt=SYSTEM_PROMPTS_IMG, timeout=420)
        dados = _extrair_json(texto)
        out = PRODUCTS / produto / "output"
        out.mkdir(parents=True, exist_ok=True)
        (out / "prompts.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify({"ok": True, "prompts": dados})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/prompts/<produto>", methods=["GET"])
def get_prompts(produto):
    f = PRODUCTS / produto / "output" / "prompts.json"
    if not f.exists():
        return jsonify([])
    return jsonify(json.loads(f.read_text(encoding="utf-8")))


@app.route("/api/prompts/<produto>", methods=["POST"])
def salvar_prompts(produto):
    body = request.get_json(force=True)
    out = PRODUCTS / produto / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompts.json").write_text(
        json.dumps(body.get("prompts", []), ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/api/gerar_imagens/<produto>", methods=["POST"])
def gerar_imagens(produto):
    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Já existe uma geração em andamento."}), 409

    def tarefa():
        try:
            gerar.gerar_criativos(produto)
        except Exception as e:  # noqa: BLE001
            out = PRODUCTS / produto / "output" / "criativos"
            out.mkdir(parents=True, exist_ok=True)
            (out / "status.json").write_text(json.dumps(
                {"total": 0, "feitos": 0, "atual": None, "arquivos": [],
                 "erros": [{"id": "-", "erro": str(e)}], "em_andamento": False},
                ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            lock.release()

    threading.Thread(target=tarefa, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/status/<produto>")
def status(produto):
    f = PRODUCTS / produto / "output" / "criativos" / "status.json"
    if f.exists():
        try:
            return jsonify(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return jsonify({"total": 0, "feitos": 0, "atual": None, "arquivos": [],
                    "erros": [], "em_andamento": False})


@app.route("/criativos/<produto>/<path:arquivo>")
def criativo(produto, arquivo):
    pasta = PRODUCTS / produto / "output" / "criativos"
    if not (pasta / arquivo).exists():
        abort(404)
    return send_from_directory(pasta, arquivo)


def _extrair_json(texto: str):
    """Extrai o array/obj JSON de uma resposta (removendo cercas de código)."""
    t = texto.strip()
    t = re.sub(r"^```(json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", t, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise
