"""Fluxo de VÍDEO UGC — blueprint montado sob /ugc no mesmo servidor Flask.

Reaproveita produtos, referências e a esteira de imagem grátis (keyframes) do
fluxo de imagem. Toda a escrita fica em videos/ e avatares/. Nenhuma rota colide
com o app de imagem (tudo vive sob o prefixo /ugc).
"""
from __future__ import annotations

import threading
import time
import uuid
import re
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # noqa: BLE001 — dotenv é opcional; FAL_KEY pode vir do ambiente
    pass

from workspace import (VIDEO_JOBS, VIDEOS, AVATARES, INFLUENCIADORES, PRODUCTS,
                       atomic_write_json, atomic_write_text,
                       avatar_dir, carregar_config, ler_json, pessoa_dir, product_dir,
                       safe_descendant, tipo_produto, video_dir)
from app.pipeline import clipes as clipes_mod
from app.pipeline import keyframes as keyframes_mod
from app.pipeline import montagem as montagem_mod
from app.pipeline import roteiro as roteiro_mod
from app.pipeline import copy_ugc as copy_ugc_mod
from app.pipeline import voz as voz_mod
from app.pipeline._status import JobStatus

ugc = Blueprint("ugc", __name__, url_prefix="/ugc")
TEMPLATES = Path(__file__).resolve().parent / "templates"


def _erro(msg, code=400):
    return jsonify({"ok": False, "erro": str(msg)}), code


def _chave(produto, vid):
    return f"{produto}/{vid}"


def _mtime(p: Path) -> int:
    try:
        return int(p.stat().st_mtime)
    except OSError:
        return 0


def _rodar_em_thread(chave, alvo, *args, **kwargs) -> bool:
    lock = VIDEO_JOBS.lock(chave)
    if not lock.acquire(blocking=False):
        return False
    cancel = VIDEO_JOBS.cancel(chave)
    cancel.clear()

    def _run():
        try:
            alvo(*args, cancel_event=cancel, **kwargs)
        except Exception as e:  # noqa: BLE001
            try:
                d = video_dir(args[0], args[1])
                st = ler_json(d / "status.json") or {}
                st.update({"em_andamento": False, "atualizado": time.time(),
                           "erros": (st.get("erros") or []) + [{"item": "job", "erro": str(e)}]})
                atomic_write_json(d / "status.json", st)
            except Exception:  # noqa: BLE001
                pass
        finally:
            lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


# ---------------------------------------------------------------- página
@ugc.get("")
@ugc.get("/")
def pagina():
    return send_from_directory(TEMPLATES, "ugc.html")


# ---------------------------------------------------------------- produtos/config
@ugc.get("/api/produtos")
def produtos():
    itens = []
    if PRODUCTS.exists():
        for p in sorted(PRODUCTS.iterdir()):
            if p.is_dir() and not p.name.startswith("_") and (p / "config.md").exists():
                refs = [r for r in (p / "referencia").glob("*") if r.is_file()] \
                    if (p / "referencia").exists() else []
                itens.append({"nome": p.name, "tem_referencia": bool(refs)})
    return jsonify({"ok": True, "produtos": itens})


@ugc.get("/api/config")
def config_api():
    cfg = carregar_config()
    v = cfg.get("video", {})
    return jsonify({"ok": True, "motor": "veo",
                    "modelo_veo": v.get("modelo_veo", "veo_fast"),
                    "precos_usd": v.get("precos_usd", {})})


@ugc.get("/api/tipo_produto/<produto>")
def obter_tipo_produto(produto):
    try:
        product_dir(produto)
        return jsonify({"ok": True, "tipo": tipo_produto(produto)})
    except ValueError as e:
        return _erro(e, 404)


@ugc.post("/api/tipo_produto/<produto>")
def salvar_tipo_produto(produto):
    dado = request.get_json(force=True) or {}
    tipo = dado.get("tipo")
    if tipo not in {"digital", "fisico"}:
        return _erro("Tipo de produto inválido.")
    try:
        p = product_dir(produto)
        cfg = p / "config.md"
        texto = cfg.read_text(encoding="utf-8", errors="replace") if cfg.exists() else f"# Configuração do produto — {produto}\n"
        linha = f"- **Tipo:** {tipo}"
        if re.search(r"(?im)^\s*-\s*\*\*tipo\*\*\s*:.*$", texto):
            texto = re.sub(r"(?im)^\s*-\s*\*\*tipo\*\*\s*:.*$", linha, texto, count=1)
        else:
            texto = texto.rstrip() + "\n\n## Produto\n" + linha + "\n"
        atomic_write_text(cfg, texto)
        return jsonify({"ok": True, "tipo": tipo})
    except ValueError as e:
        return _erro(e, 404)


# ---------------------------------------------------------------- avatares
@ugc.get("/api/avatares")
def listar_avatares():
    itens = []
    if AVATARES.exists():
        for a in sorted(AVATARES.iterdir()):
            if not a.is_dir() or a.name.startswith("."):
                continue
            refs = sorted(f.name for f in (a / "referencia").glob("*.png")) \
                if (a / "referencia").exists() else []
            st = ler_json(a / "status.json") or {}
            itens.append({
                "nome": a.name,
                "tipo": "avatar",
                "perfil": (a / "perfil.md").read_text(encoding="utf-8", errors="replace")
                if (a / "perfil.md").exists() else "",
                "voz": ler_json(a / "voz" / "voz.json") or {},
                "referencias": refs,
                "gerando": bool(st.get("em_andamento")) and (time.time() - float(st.get("atualizado") or 0)) < 90,
                "erros": st.get("erros") or [],
            })
    # Influenciadores REAIS (o expert) — mesma estrutura de pasta, entram como "quem aparece".
    if INFLUENCIADORES.exists():
        for a in sorted(INFLUENCIADORES.iterdir()):
            if not a.is_dir() or a.name.startswith("."):
                continue
            ref_dir = a / "referencia"
            refs = sorted(f.name for f in ref_dir.iterdir()
                          if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}) if ref_dir.exists() else []
            itens.append({
                "nome": a.name,
                "tipo": "influenciador",
                "perfil": (a / "perfil.md").read_text(encoding="utf-8", errors="replace")
                if (a / "perfil.md").exists() else "",
                "voz": ler_json(a / "voz" / "voz.json") or {},
                "referencias": refs,
                "gerando": False,
                "erros": [],
            })
    return jsonify({"ok": True, "avatares": itens})


def _gerar_refs_avatar(nome, cancel_event=None):
    a = avatar_dir(nome)
    perfil = (a / "perfil.md").read_text(encoding="utf-8", errors="replace")
    ref_dir = a / "referencia"
    ref_dir.mkdir(exist_ok=True)
    status = JobStatus(a / "status.json", "avatar_refs", 3)
    base = ("Foto CASEIRA vertical 9:16 tirada com celular (estética UGC real, luz natural de "
            "ambiente, leve grão, sem estúdio, sem texto, sem logo) da SEGUINTE pessoa, num cômodo "
            "de casa simples e realista:\n" + perfil)
    angulos = [
        ("ref_01_busto.png", "Enquadramento: busto frontal, olhando pra câmera, expressão simpática."),
        ("ref_02_corpo.png", "Enquadramento: meio corpo em pé, mesma roupa e mesmo cômodo."),
        ("ref_03_perfil.png", "Enquadramento: meio corpo em ângulo 3/4, mesma roupa e mesmo cômodo."),
    ]
    from backends import codex_backend as be
    cfg = carregar_config().get("keyframes", {})
    feitos = []
    for arq, ang in angulos:
        if cancel_event is not None and cancel_event.is_set():
            break
        status.comecou(arq)
        try:
            refs = feitos[:1]
            extra = ("\nAS FOTOS ANEXADAS SÃO A MESMA PESSOA E O MESMO CÔMODO: mantenha rosto, "
                     "cabelo, corpo, roupa e ambiente IDÊNTICOS.") if refs else ""
            out = ref_dir / arq
            # Sem refs (1ª foto do avatar): o Codex assume produto anexado por padrão e recusa;
            # instruímos explicitamente a gerar a pessoa só do texto.
            anexos = ("As fotos anexadas são a própria pessoa (identidade) — mantenha idêntica."
                      if refs else
                      "NÃO há imagens anexadas. Gere a pessoa inteiramente a partir da descrição "
                      "textual abaixo, sem depender de nenhuma referência. Passe só o texto ao $imagegen.")
            be.generate(base + "\n" + ang + extra, refs, out, size=cfg.get("size", "1024x1536"),
                        timeout=int(cfg.get("timeout", 600)), cancel_event=cancel_event,
                        reasoning=(cfg.get("reasoning") or None), model=(cfg.get("img_model") or None),
                        anexos_desc=anexos)
            feitos.append(out)
            status.terminou(arq)
        except Exception as e:  # noqa: BLE001
            status.terminou(arq, erro=str(e))
    status.fim(cancelado=bool(cancel_event is not None and cancel_event.is_set()))


@ugc.post("/api/avatares")
def criar_avatar():
    dado = request.get_json(force=True) or {}
    nome = (dado.get("nome") or "").strip()
    descricao = (dado.get("descricao") or "").strip()
    if not nome or not descricao:
        return _erro("Informe nome e descrição do avatar.")
    try:
        a = avatar_dir(nome, create=True)
    except ValueError as e:
        return _erro(e)
    atomic_write_text(a / "perfil.md", descricao)
    (a / "voz").mkdir(exist_ok=True)
    cfg = carregar_config().get("voz", {})
    voz = {"engine": (dado.get("engine") or cfg.get("engine", "edge")).lower(),
           "edge_voice": dado.get("edge_voice") or cfg.get("voz_padrao"),
           "rate": dado.get("rate") or "+0%"}
    if voz["engine"] == "eleven":
        from backends.tts_eleven_backend import VOICE_PADRAO, MODELO_PADRAO
        voz["voice_id"] = dado.get("voice_id") or VOICE_PADRAO
        voz["model_id"] = dado.get("model_id") or MODELO_PADRAO
    atomic_write_json(a / "voz" / "voz.json", voz)
    if not _rodar_em_thread(f"avatar/{nome}", lambda cancel_event=None: _gerar_refs_avatar(nome, cancel_event)):
        return _erro("Já existe uma geração em andamento para este avatar.", 409)
    return jsonify({"ok": True, "nome": nome})


@ugc.post("/api/avatar_refs/<nome>")
def regerar_refs_avatar(nome):
    try:
        avatar_dir(nome)
    except ValueError as e:
        return _erro(e, 404)
    if not _rodar_em_thread(f"avatar/{nome}", lambda cancel_event=None: _gerar_refs_avatar(nome, cancel_event)):
        return _erro("Já existe uma geração em andamento para este avatar.", 409)
    return jsonify({"ok": True})


@ugc.get("/avatar_media/<nome>/<path:arquivo>")
def avatar_media(nome, arquivo):
    a = avatar_dir(nome)
    alvo = safe_descendant(a, arquivo, suffixes={".png", ".jpg", ".jpeg", ".webp", ".wav"})
    return send_from_directory(alvo.parent, alvo.name)


@ugc.get("/api/vozes")
def vozes():
    from backends.tts_edge_backend import VOZES_PT_BR
    return jsonify({"ok": True, "vozes": VOZES_PT_BR})


@ugc.post("/api/voz_preview")
def voz_preview():
    dado = request.get_json(force=True) or {}
    engine = (dado.get("engine") or "edge").lower()
    voz = {"engine": engine,
           "edge_voice": dado.get("edge_voice") or "pt-BR-FranciscaNeural",
           "rate": dado.get("rate") or "+0%",
           "voice_id": dado.get("voice_id") or None,
           "model_id": dado.get("model_id") or None}
    texto = dado.get("texto") or "Oi! Essa é a minha voz. Eu recomendo demais esse produto."
    tmp = VIDEOS / ".previews"
    tmp.mkdir(parents=True, exist_ok=True)
    out = tmp / f"{uuid.uuid4().hex}.wav"
    try:
        voz_mod.preview_voz(texto, voz, out)
    except Exception as e:  # noqa: BLE001
        return _erro(f"Falha no TTS: {e}", 500)
    return jsonify({"ok": True, "url": f"/ugc/preview_audio/{out.name}"})


@ugc.get("/preview_audio/<arquivo>")
def preview_audio(arquivo):
    alvo = safe_descendant(VIDEOS / ".previews", arquivo, suffixes={".wav"})
    return send_from_directory(alvo.parent, alvo.name)


# ---------------------------------------------------------------- vídeos/roteiro
@ugc.get("/api/copy_chat/<produto>")
def obter_copy_chat(produto):
    try:
        product_dir(produto)
    except ValueError as e:
        return _erro(e, 404)
    return jsonify({"ok": True, "chat": copy_ugc_mod.carregar_chat(produto)})


@ugc.post("/api/copy_chat/<produto>")
def conversar_copy_chat(produto):
    dado = request.get_json(force=True) or {}
    mensagem = (dado.get("mensagem") or "").strip()
    if not mensagem:
        return _erro("Escreva o que você quer criar.")
    modo = dado.get("modo")
    if modo not in {"ugc_depoimento", "organico_camuflado"}:
        return _erro("Marque UGC ou OrgÃ¢nico antes de pedir os roteiros.", 400)
    try:
        r = copy_ugc_mod.conversar(produto, mensagem, dado.get("modelo"), modo,
                                   dado.get("session_id"))
        return jsonify({"ok": True, **r})
    except Exception as e:  # noqa: BLE001
        return _erro(e, 500)


@ugc.get("/api/videos/<produto>")
def listar_videos(produto):
    try:
        product_dir(produto)
    except ValueError as e:
        return _erro(e, 404)
    base = VIDEOS / produto
    itens = []
    if base.exists():
        for v in sorted(base.iterdir(), reverse=True):
            rot = ler_json(v / "roteiro.json")
            if rot:
                itens.append({"id": v.name, "estado": rot.get("estado"), "avatar": rot.get("avatar"),
                              "cenas": len(rot.get("cenas") or []), "criado": rot.get("criado")})
    return jsonify({"ok": True, "videos": itens})


@ugc.post("/api/videos/<produto>")
def criar_video(produto):
    dado = request.get_json(force=True) or {}
    copy = (dado.get("copy") or "").strip()
    tipo_escolhido = dado.get("tipo_produto")
    formato_escolhido = dado.get("formato_video")
    if tipo_escolhido not in {"digital", "fisico"}:
        return _erro("Marque Fisico ou Digital antes de criar o roteiro.", 400)
    if formato_escolhido not in {"ugc_depoimento", "organico_camuflado"}:
        return _erro("Marque UGC ou Organico antes de criar o roteiro.", 400)
    if tipo_escolhido != tipo_produto(produto):
        return _erro("O tipo escolhido nao esta salvo no produto. Selecione Fisico/Digital novamente e tente de novo.", 409)
    if not copy:
        return _erro("Cole a copy do anúncio.")
    # Valor do picker vem como "tipo::nome" (avatar UGC ou influenciador/expert).
    avatar_raw = (dado.get("avatar") or "").strip() or None
    pessoa_tipo, avatar = "avatar", avatar_raw
    if avatar_raw and "::" in avatar_raw:
        pessoa_tipo, avatar = avatar_raw.split("::", 1)
    try:
        if avatar:
            pessoa_dir(avatar, pessoa_tipo)
        roteiro = roteiro_mod.criar_roteiro(produto, copy, avatar, modelo=dado.get("modelo") or None,
                                            config_video=carregar_config().get("video", {}),
                                            pessoa_tipo=pessoa_tipo,
                                            formato_video=formato_escolhido)
    except Exception as e:  # noqa: BLE001
        return _erro(e, 500)
    return jsonify({"ok": True, "roteiro": roteiro})


@ugc.get("/api/roteiro/<produto>/<vid>")
def obter_roteiro(produto, vid):
    try:
        d = video_dir(produto, vid)
    except ValueError as e:
        return _erro(e, 404)
    return jsonify({"ok": True, "roteiro": ler_json(d / "roteiro.json")})


@ugc.post("/api/roteiro/<produto>/<vid>")
def editar_roteiro(produto, vid):
    dado = request.get_json(force=True) or {}
    try:
        d = video_dir(produto, vid)
    except ValueError as e:
        return _erro(e, 404)
    rot = ler_json(d / "roteiro.json")
    clipe_zerado = {"arquivo": None, "gerado": False, "fal_request_id": None,
                    "erro": None, "lipsync_aplicado": False}
    for nova in (dado.get("cenas") or []):
        for c in rot["cenas"]:
            if c["n"] != nova.get("n"):
                continue
            if "prompt_keyframe" in nova and nova["prompt_keyframe"] != c.get("prompt_keyframe"):
                c["keyframe"] = {"arquivo": None, "aprovado": False,
                                 "tentativas": c["keyframe"].get("tentativas", 0)}
                c["clipe"] = dict(clipe_zerado)
            if "prompt_movimento" in nova and nova["prompt_movimento"] != c.get("prompt_movimento"):
                c["clipe"] = dict(clipe_zerado)
            if "narracao" in nova and nova["narracao"] != c.get("narracao"):
                c["audio"] = {"arquivo": None, "duracao_s": None}
            for campo in ("narracao", "prompt_keyframe", "prompt_movimento", "tipo"):
                if campo in nova:
                    c[campo] = nova[campo]
    atomic_write_json(d / "roteiro.json", rot)
    return jsonify({"ok": True, "roteiro": rot})


@ugc.post("/api/roteiro_chat/<produto>/<vid>")
def chat_roteiro(produto, vid):
    dado = request.get_json(force=True) or {}
    instrucao = (dado.get("mensagem") or "").strip()
    if not instrucao:
        return _erro("Mensagem vazia.")
    try:
        roteiro = roteiro_mod.refinar_roteiro(produto, vid, instrucao)
    except Exception as e:  # noqa: BLE001
        return _erro(e, 500)
    return jsonify({"ok": True, "roteiro": roteiro})


@ugc.post("/api/aprovar_roteiro/<produto>/<vid>")
def aprovar_roteiro(produto, vid):
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    rot["estado"] = "roteiro_aprovado"
    atomic_write_json(d / "roteiro.json", rot)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- keyframes
@ugc.post("/api/gerar_keyframes/<produto>/<vid>")
def gerar_keyframes(produto, vid):
    dado = request.get_json(silent=True) or {}
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json") or {}
    tipo_atual = tipo_produto(produto)
    if rot.get("tipo_produto") and rot.get("tipo_produto") != tipo_atual:
        return _erro(
            f"O roteiro foi criado como produto {rot['tipo_produto']}, mas o produto agora esta marcado "
            f"como {tipo_atual}. Crie um novo video para regenerar as cenas com o tipo correto.", 409)
    if JobStatus.em_andamento(d / "status.json"):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
    if not _rodar_em_thread(_chave(produto, vid), keyframes_mod.gerar_keyframes, produto, vid, dado.get("ns") or None):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
    return jsonify({"ok": True})


@ugc.post("/api/refinar_keyframe/<produto>/<vid>/<int:n>")
def refinar_keyframe(produto, vid, n):
    dado = request.get_json(silent=True) or {}
    extra = (dado.get("instrucao") or "").strip() or None
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    if not next((c for c in rot["cenas"] if c["n"] == n), None):
        return _erro("Cena não encontrada.", 404)

    def _job(produto_, vid_, cancel_event=None):
        d_ = video_dir(produto_, vid_)
        rot_ = ler_json(d_ / "roteiro.json")
        cena_ = next(c for c in rot_["cenas"] if c["n"] == n)
        status = JobStatus(d_ / "status.json", "keyframes", 1)
        try:
            status.comecou(f"cena_{n:02d}")
            nome = keyframes_mod.gerar_um_keyframe(rot_, cena_, d_ / "keyframes",
                                                   cancel_event=cancel_event, extra=extra)
            atual = ler_json(d_ / "roteiro.json")
            for c in atual["cenas"]:
                if c["n"] == n:
                    c["keyframe"].update({"arquivo": nome, "aprovado": False,
                                          "tentativas": int(c["keyframe"].get("tentativas") or 0) + 1})
                    c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                                  "erro": None, "lipsync_aplicado": False}
            atomic_write_json(d_ / "roteiro.json", atual)
            status.terminou(f"cena_{n:02d}")
        except Exception as e:  # noqa: BLE001
            status.terminou(f"cena_{n:02d}", erro=str(e))
        finally:
            status.fim()

    if not _rodar_em_thread(_chave(produto, vid), _job, produto, vid):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
    return jsonify({"ok": True})


@ugc.post("/api/aprovar_keyframe/<produto>/<vid>/<int:n>")
def aprovar_keyframe(produto, vid, n):
    dado = request.get_json(silent=True) or {}
    aprovado = bool(dado.get("aprovado", True))
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    for c in rot["cenas"]:
        if c["n"] == n:
            c["keyframe"]["aprovado"] = aprovado
    if all(c["keyframe"]["aprovado"] for c in rot["cenas"]):
        rot["estado"] = "keyframes_aprovados"
    atomic_write_json(d / "roteiro.json", rot)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- clipes/montagem
@ugc.post("/api/gerar_clipes/<produto>/<vid>")
def gerar_clipes(produto, vid):
    dado = request.get_json(silent=True) or {}
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    pendentes = [c for c in rot["cenas"] if not c["clipe"]["gerado"]]
    sem_kf = [c["n"] for c in pendentes if not c["keyframe"]["arquivo"]]
    if sem_kf:
        return _erro(f"Cenas sem keyframe: {sem_kf}. Gere os keyframes antes.")
    nao_aprov = [c["n"] for c in pendentes if not c["keyframe"]["aprovado"]]
    if nao_aprov and not dado.get("forcar"):
        return _erro(f"Keyframes não aprovados: {nao_aprov}. Aprove todos (ou envie forcar=true).")
    if JobStatus.em_andamento(d / "status.json"):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
    if not _rodar_em_thread(_chave(produto, vid), clipes_mod.gerar_clipes, produto, vid,
                            motor=dado.get("motor") or None, retomar=bool(dado.get("retomar"))):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
    return jsonify({"ok": True})


@ugc.post("/api/regerar_clipe/<produto>/<vid>/<int:n>")
def regerar_clipe(produto, vid, n):
    dado = request.get_json(silent=True) or {}
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    encontrou = False
    for c in rot["cenas"]:
        if c["n"] == n and not dado.get("retomar"):
            encontrou = True
            instrucao = (dado.get("instrucao") or "").strip()
            if instrucao:
                c["instrucao_clipe"] = instrucao
            c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                          "erro": None, "lipsync_aplicado": False}
    if not encontrou and not dado.get("retomar"):
        return _erro("Take nao encontrado.", 404)
    if not dado.get("retomar"):
        rot["estado"] = "keyframes_aprovados"
    atomic_write_json(d / "roteiro.json", rot)
    if not _rodar_em_thread(_chave(produto, vid), clipes_mod.gerar_clipes, produto, vid,
                            motor=dado.get("motor") or None, ns=[n], retomar=bool(dado.get("retomar"))):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
    return jsonify({"ok": True})


@ugc.post("/api/edicao/<produto>/<vid>")
def salvar_edicao(produto, vid):
    dado = request.get_json(force=True) or {}
    cortes = dado.get("cortes") or []
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json") or {}
    por_n = {int(x.get("n")): x for x in cortes if str(x.get("n", "")).isdigit()}
    for c in rot.get("cenas") or []:
        x = por_n.get(int(c["n"]))
        if not x:
            continue
        inicio = max(0.0, float(x.get("inicio_s") or 0.0))
        fim = max(0.0, float(x.get("fim_s") or 0.0))
        if fim and fim <= inicio + 0.10:
            return _erro(f"Corte invalido na cena {c['n']}: o fim precisa ser maior que o inicio.", 400)
        c["edicao"] = {"inicio_s": inicio, "fim_s": fim, "remover": bool(x.get("remover"))}
    atomic_write_json(d / "roteiro.json", rot)
    return jsonify({"ok": True})


@ugc.post("/api/montar/<produto>/<vid>")
def montar(produto, vid):
    dado = request.get_json(silent=True) or {}

    def _job(produto_, vid_, cancel_event=None):
        d_ = video_dir(produto_, vid_)
        status = JobStatus(d_ / "status.json", "montagem", 1)
        try:
            status.comecou("montagem")
            montagem_mod.montar(produto_, vid_, legendas=bool(dado.get("legendas", False)))
            status.terminou("montagem")
        except Exception as e:  # noqa: BLE001
            status.terminou("montagem", erro=str(e))
        finally:
            status.fim()

    if not _rodar_em_thread(_chave(produto, vid), _job, produto, vid):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
    return jsonify({"ok": True})


@ugc.post("/api/parar/<produto>/<vid>")
def parar(produto, vid):
    VIDEO_JOBS.cancel(_chave(produto, vid)).set()
    return jsonify({"ok": True})


@ugc.get("/api/status/<produto>/<vid>")
def status(produto, vid):
    try:
        d = video_dir(produto, vid)
    except ValueError as e:
        return _erro(e, 404)
    st = ler_json(d / "status.json") or {}
    if st.get("em_andamento") and (time.time() - float(st.get("atualizado") or 0)) > 90:
        st["em_andamento"] = False
        st.setdefault("erros", []).append({"item": "job", "erro": "Execução interrompida (sem batimento)."})
        atomic_write_json(d / "status.json", st)
    rot = ler_json(d / "roteiro.json") or {}
    cenas = []
    for c in rot.get("cenas") or []:
        kf, cl = c["keyframe"]["arquivo"], c["clipe"]["arquivo"]
        cenas.append({
            "n": c["n"], "tipo": c["tipo"], "narracao": c["narracao"],
            "instrucao_clipe": c.get("instrucao_clipe") or "",
            "prompt_keyframe": c["prompt_keyframe"], "prompt_movimento": c["prompt_movimento"],
            "keyframe": {**c["keyframe"],
                         "url": f"/ugc/media/{produto}/{vid}/keyframes/{kf}?t={_mtime(d / 'keyframes' / kf)}" if kf else None},
            "clipe": {**c["clipe"],
                      "url": f"/ugc/media/{produto}/{vid}/clipes/{cl}?t={_mtime(d / 'clipes' / cl)}" if cl else None},
            "audio": c.get("audio") or {},
            "edicao": c.get("edicao") or {"inicio_s": 0, "fim_s": 0, "remover": False},
        })
    final = d / "final" / "video.mp4"
    full = carregar_config()
    vcfg = full.get("video", {})
    # Veo (omni): preço por clipe (5s) do modelo escolhido. Sai do crédito Google.
    preco_clipe = float((vcfg.get("precos_usd") or {}).get(vcfg.get("modelo_veo", "veo_fast"), 0.75))
    est = 0.0
    for c in rot.get("cenas") or []:
        if c["clipe"]["gerado"]:
            continue
        est += preco_clipe
    return jsonify({"ok": True, "status": st, "estado": rot.get("estado"), "avatar": rot.get("avatar"),
                    "tipo_produto": rot.get("tipo_produto", "fisico"),
                    "pessoa_tipo": rot.get("pessoa_tipo", "avatar"),
                    "chat": rot.get("chat") or [], "cenas": cenas,
                    "estimativa_usd": round(est, 2),
                    "final_url": f"/ugc/media/{produto}/{vid}/final/video.mp4?t={_mtime(final)}"
                    if final.exists() and rot.get("estado") == "montado" else None})


@ugc.get("/media/<produto>/<vid>/<path:arquivo>")
def media(produto, vid, arquivo):
    d = video_dir(produto, vid)
    alvo = safe_descendant(d, arquivo, suffixes={".png", ".jpg", ".mp4", ".wav", ".ass"})
    return send_from_directory(alvo.parent, alvo.name)
