"""Fluxo de VÍDEO UGC — blueprint montado sob /ugc no mesmo servidor Flask.

Reaproveita produtos, referências e a esteira de imagem grátis (keyframes) do
fluxo de imagem. Toda a escrita fica em videos/ e avatares/. Nenhuma rota colide
com o app de imagem (tudo vive sob o prefixo /ugc).
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
import re
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from workspace import (VIDEO_JOBS, VIDEOS, AVATARES, INFLUENCIADORES, PRODUCTS,
                       atomic_write_json, atomic_write_text,
                       avatar_dir, carregar_config, carregar_env, ler_json,
                       pessoa_dir, product_dir,
                       safe_descendant, tipo_produto, video_dir)

# Carrega config/.env pelo DATA_ROOT do workspace (funciona também no app
# empacotado, onde __file__ vive no bundle só-leitura _MEIPASS).
carregar_env()
from app.pipeline import clipes as clipes_mod
from app import nosleep
from app.pipeline import keyframes as keyframes_mod
from app.pipeline import montagem as montagem_mod
from app.pipeline import roteiro as roteiro_mod
from app.pipeline import copy_ugc as copy_ugc_mod
from app.pipeline import voz as voz_mod
from app.pipeline import formatos_video as fv
from app.pipeline import qualidade as qualidade_mod
from app.pipeline import inserts as inserts_mod
from app.pipeline._status import JobStatus

ugc = Blueprint("ugc", __name__, url_prefix="/ugc")
TEMPLATES = Path(__file__).resolve().parent / "templates"


def _erro(msg, code=400):
    # Registra no console embutido (traceback quando for exceção) pra depurar sem terminal.
    try:
        from app import console_log
        import traceback as _tb
        if isinstance(msg, BaseException):
            console_log.registrar("ERRO", "".join(
                _tb.format_exception(type(msg), msg, msg.__traceback__)))
        else:
            console_log.registrar("ERRO", str(msg))
    except Exception:  # noqa: BLE001
        pass
    return jsonify({"ok": False, "erro": str(msg)}), code


def _chave(produto, vid):
    return f"{produto}/{vid}"


_RE_N_ROT = re.compile(r"(\d{1,2})\s*(?:roteiro|v[ií]deo|op[cç])", re.I)
_RE_N_QUALQ = re.compile(r"\b(\d{1,2})\b")


def _n_roteiros_do_texto(msg: str) -> int:
    """Reconhece a QUANTIDADE de roteiros no texto do prompt (ex.: 'quero 5 roteiros').
    Sem número, devolve 0 (o chamador usa o default de 1 por formato marcado)."""
    m = _RE_N_ROT.search(msg or "") or _RE_N_QUALQ.search(msg or "")
    if not m:
        return 0
    try:
        return max(1, min(12, int(m.group(1))))
    except (TypeError, ValueError):
        return 0


def _mtime(p: Path) -> int:
    try:
        return int(p.stat().st_mtime)
    except OSError:
        return 0


def _descartes_cena(d: Path, produto: str, vid: str, n: int) -> list[dict]:
    """Metadados e mídia das tentativas recusadas, sem expor prompts pelo endpoint de mídia."""
    base = d / "descartados" / f"cena_{n:02d}"
    itens = []
    if not base.exists():
        return itens
    for pasta in sorted(base.glob("tentativa_*"), reverse=True):
        analise = ler_json(pasta / "analise.json") or {}
        midia = next((x for x in pasta.iterdir() if x.suffix.lower() in {".mp4", ".png", ".jpg"}), None)
        rel = midia.relative_to(d).as_posix() if midia else None
        itens.append({"tentativa": pasta.name, "etapa": analise.get("etapa"),
                      "motivos": analise.get("motivos") or [],
                      "url": f"/ugc/media/{produto}/{vid}/{rel}?t={_mtime(midia)}" if midia else None,
                      "tipo": midia.suffix.lower() if midia else None})
    return itens


def _avatares_ugc() -> list[str]:
    """Nomes dos avatares UGC reais (selfie de casa). Exclui os influenciadores/experts,
    que vivem noutra pasta (INFLUENCIADORES) e têm outro papel no casting."""
    out = []
    if AVATARES.exists():
        for a in sorted(AVATARES.iterdir()):
            if not a.is_dir() or a.name.startswith("."):
                continue
            if (a / "perfil.md").exists():
                out.append(a.name)
    return out


def _escolher_avatar_ugc(produto: str) -> str | None:
    """Casting 'auto' (só faz sentido em formato SOLO): escolhe UM avatar UGC existente.
    Determinístico por produto — o mesmo produto reusa sempre o mesmo avatar (pessoa
    recorrente do lote). Devolve None se não houver nenhum avatar UGC cadastrado."""
    nomes = _avatares_ugc()
    if not nomes:
        return None
    idx = int(hashlib.sha1(produto.encode("utf-8")).hexdigest(), 16) % len(nomes)
    return nomes[idx]


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

    # nosleep.envolver: segura a trava de energia enquanto o job roda. Sem isto o Mac
    # suspende no meio e os processos externos voltam quebrados ('went to sleep mid-response').
    threading.Thread(target=nosleep.envolver(_run), daemon=True).start()
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


# ---------------------------------------------------------------- formatos de vídeo
@ugc.route("/api/formatos_video/<produto>", methods=["GET", "POST"])
def formatos_video_api(produto):
    """Formatos de vídeo ativos do produto (padrao/fala_faz/top5/...). O 1º da lista
    é o ativo e decide qual cérebro de copy/roteirista o pipeline usa."""
    try:
        product_dir(produto)
    except ValueError as e:
        return _erro(e, 404)
    if request.method == "GET":
        return jsonify({"ok": True, "catalogo": fv.catalogo_publico(),
                        "formatos": fv.ler_formatos(produto)})
    dado = request.get_json(silent=True) or {}
    salvos = fv.escrever_formatos(produto, [str(x) for x in (dado.get("formatos") or [])])
    return jsonify({"ok": True, "formatos": salvos})


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
    modelo = dado.get("modelo")
    # Formatos marcados no popup. A QUANTIDADE de roteiros é reconhecida no PRÓPRIO
    # texto do prompt (ex.: "quero 5 roteiros"), igual ao fluxo de estáticos; sem
    # número no texto, o default é 1 por formato marcado.
    formatos_sel = [f for f in (dado.get("formatos") or []) if fv.existe(f)]
    n_roteiros = _n_roteiros_do_texto(mensagem)

    if len(formatos_sel) > 1:
        # Mix de formatos: 1 opção por item do plano, geradas EM PARALELO com ângulos
        # distintos (uma thread por opção). Erros por item não derrubam os demais.
        n = n_roteiros or len(formatos_sel)
        plano = fv.distribuir(n, formatos_sel)          # ex.: [padrao,wikihow,noticia,padrao,...]
        r = copy_ugc_mod.gerar_opcoes_paralelo(produto, mensagem, modelo, plano)
        opcoes = r.get("opcoes") or []
        if not opcoes:
            return _erro("Não consegui gerar roteiros neste mix (limite do modelo). Tente de novo.", 500)
        from collections import Counter
        contagem = Counter(o.get("formato") for o in opcoes)
        textos = [f"**{fv.info(fmt).get('label', fmt)}** ({contagem[fmt]})"
                  for fmt in formatos_sel if contagem.get(fmt)]
        vazios = [fv.info(fmt).get("label", fmt) for fmt in formatos_sel if not contagem.get(fmt)]
        resp = "Roteiros do mix: " + ", ".join(textos) + ". Escolha os que quer criar."
        if vazios:
            resp += " ⚠️ Não vieram: " + ", ".join(vazios) + " (throttle). Reenvie pra completar."
        return jsonify({"ok": True, "opcoes": opcoes, "session_id": None, "resposta": resp})

    # Formato único: o modo (UGC x Nativo) é derivado do próprio formato.
    formato = (formatos_sel[0] if formatos_sel else (dado.get("formato") or "padrao"))
    if not fv.existe(formato):
        formato = "padrao"
    # N explícito no texto (ex.: "quero 5 roteiros"): gera as N opções EM PARALELO,
    # cada uma num ângulo distinto. Sem número, mantém a chamada única (o modelo decide
    # a quantidade e a diversidade sozinho, como antes).
    if n_roteiros >= 2:
        r = copy_ugc_mod.gerar_opcoes_paralelo(produto, mensagem, modelo, [formato] * n_roteiros)
        if not (r.get("opcoes") or []):
            return _erro("Não consegui gerar os roteiros (limite do modelo). Tente de novo.", 500)
        return jsonify({"ok": True, "opcoes": r["opcoes"], "session_id": None,
                        "resposta": r.get("resposta") or "Escolha uma ou mais opções abaixo."})
    try:
        r = copy_ugc_mod.conversar(produto, mensagem, modelo, fv.modo_do_formato(formato),
                                   dado.get("session_id"), formato=formato)
        for o in (r.get("opcoes") or []):
            # FORÇA o id do formato (ex.: "entrevista"), não deixa o `setdefault` preservar
            # o MODO ("ugc_depoimento") que o LLM às vezes ecoa — senão o formato se perde ao
            # criar o vídeo (caía em "padrao" e virava depoimento solo, sem two-shot).
            o["formato"] = formato
            o["formato_label"] = fv.info(formato).get("label", formato)
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
                fmt_v = rot.get("formato_video") or "padrao"
                itens.append({"id": v.name, "estado": rot.get("estado"), "avatar": rot.get("avatar"),
                              "cenas": len(rot.get("cenas") or []), "criado": rot.get("criado"),
                              "formato": fmt_v, "formato_label": fv.info(fmt_v).get("label", fmt_v)})
    return jsonify({"ok": True, "videos": itens})


@ugc.post("/api/videos/<produto>")
def criar_video(produto):
    dado = request.get_json(force=True) or {}
    copy = (dado.get("copy") or "").strip()
    tipo_escolhido = dado.get("tipo_produto")
    # Formato escolhido no popup. padrao/nativo são os modos base (viram formato_video
    # = o modo UGC/Nativo do cérebro base); os demais formatos viram o próprio id.
    formato = dado.get("formato") or "padrao"
    if not fv.existe(formato):
        formato = "padrao"
    if tipo_escolhido not in {"digital", "fisico"}:
        return _erro("Marque Fisico ou Digital antes de criar o roteiro.", 400)
    if formato in ("padrao", "nativo"):
        formato_video = fv.modo_do_formato(formato)   # ugc_depoimento | organico_camuflado
    else:
        formato_video = formato
    if tipo_escolhido != tipo_produto(produto):
        return _erro("O tipo escolhido nao esta salvo no produto. Selecione Fisico/Digital novamente e tente de novo.", 409)
    if not copy:
        return _erro("Cole a copy do anúncio.")
    # CASTING POR FORMATO/PAPEL — resolve o campo `avatar` do contrato antes do roteiro:
    #   "auto"              -> IA escolhe um avatar UGC (só SOLO; em multi vira elenco gerado)
    #   ""                  -> sem pessoa (produto + mãos, sem rosto)
    #   "gerado"            -> multi-pessoa; o Veo gera o elenco, SEM referência de avatar
    #   "avatar::Nome"      -> avatar UGC específico (solo)
    #   "influenciador::Nome" -> expert oficial (solo: a pessoa; multi: a AUTORIDADE, papel A)
    avatar_raw = (dado.get("avatar") or "").strip()
    multi = fv.multi_pessoa(formato)
    pessoa_tipo, avatar, elenco_gerado = "avatar", None, False
    if avatar_raw == "gerado":
        # Elenco inteiro gerado pelo Veo (coerente com o cenário), sem avatar de casa.
        elenco_gerado = True
    elif avatar_raw == "auto":
        if multi:
            # Avatar de casa buga cena multi-pessoa: cai pra elenco gerado.
            elenco_gerado = True
        else:
            escolhido = _escolher_avatar_ugc(produto)
            if escolhido:
                avatar, pessoa_tipo = escolhido, "avatar"
            # Sem nenhum UGC cadastrado: segue sem pessoa (comportamento seguro).
    elif avatar_raw and "::" in avatar_raw:
        pessoa_tipo, nome = avatar_raw.split("::", 1)
        avatar = nome.strip() or None
        if pessoa_tipo not in ("avatar", "influenciador"):
            pessoa_tipo = "avatar"
    elif avatar_raw:
        # Legado: nome cru sem prefixo de tipo -> avatar UGC.
        avatar = avatar_raw
    # avatar_raw == "" -> sem pessoa (avatar None), como antes.
    # TWO-SHOT (entrevista/experimento de rua): a DUPLA é sempre gerada junta — nunca um
    # avatar de casa solo. Força elenco gerado mesmo que um avatar tenha sido escolhido.
    if fv.two_shot(formato):
        elenco_gerado, avatar = True, None
    # A pessoa (avatar/influenciador) referenciada pode não existir NESTA máquina — ex.:
    # dados não sincronizados entre Windows e Mac. Não travar o roteiro por isso: segue
    # sem pessoa (produto + mãos), que é o comportamento seguro.
    if avatar:
        try:
            pessoa_dir(avatar, pessoa_tipo)
        except ValueError:
            avatar, pessoa_tipo = None, "avatar"
    try:
        roteiro = roteiro_mod.criar_roteiro(produto, copy, avatar, modelo=dado.get("modelo") or None,
                                            config_video=carregar_config().get("video", {}),
                                            pessoa_tipo=pessoa_tipo,
                                            formato_video=formato_video,
                                            elenco_gerado=elenco_gerado)
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


@ugc.post("/api/aceitar_keyframe/<produto>/<vid>/<int:n>")
def aceitar_keyframe(produto, vid, n):
    """Escape hatch: promove uma imagem reprovada da cena a keyframe, mesmo com o QA
    tendo reprovado (o usuário decide). Sem 'tentativa' no corpo, usa o descarte mais
    recente; com 'tentativa' (nome da pasta, ex.: 'tentativa_06_keyframe'), usa AQUELE
    descarte específico — às vezes o usuário prefere uma tentativa antiga."""
    import shutil
    dado = request.get_json(silent=True) or {}
    escolha = str(dado.get("tentativa") or "").strip()
    d = video_dir(produto, vid)
    base = d / "descartados" / f"cena_{n:02d}"
    origem = None
    if base.exists():
        if escolha:
            # safe_descendant barra path traversal ('..'/absoluto): só pastas desta cena.
            try:
                pasta = safe_descendant(base, escolha)
            except ValueError:
                return _erro("Tentativa inválida.", 400)
            if pasta.is_dir():
                origem = next((x for x in pasta.iterdir()
                               if x.suffix.lower() in {".png", ".jpg"}), None)
        else:
            for pasta in sorted(base.glob("tentativa_*"), reverse=True):  # mais recente primeiro
                img = next((x for x in pasta.iterdir() if x.suffix.lower() in {".png", ".jpg"}), None)
                if img:
                    origem = img
                    break
    if not origem:
        return _erro("Não achei essa imagem reprovada pra aceitar — clique 'Gerar de novo'.", 404)
    out_dir = d / "keyframes"
    out_dir.mkdir(parents=True, exist_ok=True)
    destino = out_dir / f"cena_{n:02d}.png"
    shutil.copy2(origem, destino)
    rot_file = d / "roteiro.json"
    atual = ler_json(rot_file) or {}
    n_desc = len(list(base.glob("tentativa_*"))) if base.exists() else 0
    for c in atual.get("cenas", []):
        if c["n"] == n:
            c["keyframe"]["arquivo"] = destino.name
            c["keyframe"]["aprovado"] = True
            c["qualidade"] = {"estado": "aprovado", "etapa": "keyframe", "tentativa": 0,
                              "motivos": [], "descartes": n_desc, "aceito_manual": True, "analise": {}}
            # keyframe novo invalida clipe antigo da cena
            c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                          "erro": None, "lipsync_aplicado": False}
    atomic_write_json(rot_file, atual)
    return jsonify({"ok": True})


# ---- LOTE: gera keyframes/clipes de VÁRIOS vídeos juntos (mix de formatos) ----
@ugc.post("/api/gerar_keyframes_lote/<produto>")
def gerar_keyframes_lote_ep(produto):
    """Junta as cenas de TODOS os vídeos do lote e gera os keyframes de 6 em 6
    (fila rolante), como nos criativos estáticos. Ex.: 5 vídeos x 8 = 40 frames."""
    dado = request.get_json(silent=True) or {}
    vids = [str(v) for v in (dado.get("vids") or []) if v]
    if not vids:
        return _erro("Nenhum vídeo no lote.", 400)
    if JobStatus.em_andamento(VIDEOS / produto / "lote_status.json"):
        return _erro("Já existe um lote em andamento.", 409)
    if not _rodar_em_thread(f"{produto}/_lote", keyframes_mod.gerar_keyframes_lote, produto, vids):
        return _erro("Já existe um lote em andamento.", 409)
    return jsonify({"ok": True, "total_videos": len(vids)})


@ugc.get("/api/status_lote/<produto>")
def status_lote(produto):
    try:
        product_dir(produto)
    except ValueError as e:
        return _erro(e, 404)
    st = ler_json(VIDEOS / produto / "lote_status.json") or {"em_andamento": False}
    return jsonify({"ok": True, "status": st})


@ugc.post("/api/gerar_clipes_lote/<produto>")
def gerar_clipes_lote_ep(produto):
    """Junta as cenas (keyframe pronto) de TODOS os vídeos do lote e gera os clipes
    (Veo, PAGO) de 6 em 6 (fila rolante), igual aos keyframes em lote. Cada clipe é
    salvo no seu próprio vídeo/cena. Roda depois dos keyframes aprovados."""
    dado = request.get_json(silent=True) or {}
    vids = [str(v) for v in (dado.get("vids") or []) if v]
    if not vids:
        return _erro("Nenhum vídeo no lote.", 400)
    if JobStatus.em_andamento(VIDEOS / produto / "lote_status.json"):
        return _erro("Já existe um lote em andamento.", 409)
    if not _rodar_em_thread(f"{produto}/_lote", clipes_mod.gerar_clipes_lote, produto, vids):
        return _erro("Já existe um lote em andamento.", 409)
    return jsonify({"ok": True, "total_videos": len(vids)})


@ugc.post("/api/montar_lote/<produto>")
def montar_lote_ep(produto):
    """Monta o vídeo FINAL de CADA vídeo do lote em paralelo (ffmpeg local, grátis).
    Cada anúncio vira 1 mp4. Progresso no mesmo lote_status.json."""
    dado = request.get_json(silent=True) or {}
    vids = [str(v) for v in (dado.get("vids") or []) if v]
    if not vids:
        return _erro("Nenhum vídeo no lote.", 400)
    if JobStatus.em_andamento(VIDEOS / produto / "lote_status.json"):
        return _erro("Já existe um lote em andamento.", 409)
    if not _rodar_em_thread(f"{produto}/_lote", montagem_mod.montar_lote, produto, vids):
        return _erro("Já existe um lote em andamento.", 409)
    return jsonify({"ok": True, "total_videos": len(vids)})


@ugc.get("/api/entregas_lote/<produto>")
def entregas_lote_ep(produto):
    """Lista os vídeos FINAIS (montados) dos vids informados (?vids=a,b,c) — pra grade
    de entregas do lote. Devolve {vid, titulo, final} (nome do mp4 em final/)."""
    pedidos = [v for v in (request.args.get("vids") or "").split(",") if v.strip()]
    itens = []
    for vid in pedidos:
        try:
            d = video_dir(produto, vid)
        except Exception:  # noqa: BLE001
            continue
        rot = ler_json(d / "roteiro.json") or {}
        final = d / "final" / "video.mp4"
        final_url = (f"/ugc/media/{produto}/{vid}/final/video.mp4?t={_mtime(final)}"
                     if final.exists() else None)
        itens.append({"vid": vid, "titulo": rot.get("titulo") or vid,
                      "estado": rot.get("estado"), "final_url": final_url})
    return jsonify({"ok": True, "entregas": itens})


def _lote_recente(produto):
    """Descobre os vídeos do ÚLTIMO lote no disco, agrupando por prefixo de batch
    `ugc_AAAAMMDD_HHMMSS` (os IDs de um mesmo lote compartilham esse prefixo e diferem
    só no sufixo `_0000N_hash`). Retorna a lista de ids do batch mais recente com 2+
    vídeos — pra a prévia funcionar mesmo sem o estado em memória (reload/rebuild)."""
    base = VIDEOS / produto
    if not base.exists():
        return []
    grupos = {}
    for v in base.iterdir():
        if not v.is_dir() or v.name.startswith("."):
            continue
        m = re.match(r"^(ugc_\d{8}_\d{6})_\d+", v.name)
        if not m:
            continue
        grupos.setdefault(m.group(1), []).append(v.name)
    lotes = [(k, sorted(vs)) for k, vs in grupos.items() if len(vs) >= 2]
    if not lotes:
        return []
    lotes.sort(key=lambda kv: kv[0], reverse=True)  # prefixo = timestamp -> mais recente 1º
    return lotes[0][1]


@ugc.get("/api/previa_lote/<produto>")
def previa_lote_ep(produto):
    """Prévia visual do lote: por vídeo, devolve as cenas com miniatura do keyframe e se
    o clipe já foi gerado. Alimenta a grade das etapas Keyframes/Clipes do lote pra dar
    feedback (sem isso a tela fica em branco depois de gerar em lote). Sem ?vids=,
    auto-detecta o lote mais recente no disco."""
    pedidos = [v for v in (request.args.get("vids") or "").split(",") if v.strip()]
    if not pedidos:
        pedidos = _lote_recente(produto)
    com_dur = request.args.get("durs") in ("1", "true", "yes")   # editor da Final pede a duração real do clipe
    itens = []
    for vid in pedidos:
        try:
            d = video_dir(produto, vid)
        except Exception:  # noqa: BLE001
            continue
        rot = ler_json(d / "roteiro.json") or {}
        cenas = []
        for c in rot.get("cenas") or []:
            kf, cl = c["keyframe"]["arquivo"], c["clipe"]["arquivo"]
            clipe_ok = bool(cl) and bool(c["clipe"].get("gerado"))
            ed = c.get("edicao") or {}
            cenas.append({
                "n": c["n"],
                "keyframe_url": (f"/ugc/media/{produto}/{vid}/keyframes/{kf}?t={_mtime(d / 'keyframes' / kf)}"
                                 if kf else None),
                "keyframe_aprovado": bool(c["keyframe"].get("aprovado")),
                "clipe_ok": clipe_ok,
                "clipe_url": (f"/ugc/media/{produto}/{vid}/clipes/{cl}?t={_mtime(d / 'clipes' / cl)}"
                              if clipe_ok else None),
                # dados pro EDITOR de timeline (aparar gorduras): corte atual + narração
                "inicio_s": float(ed.get("inicio_s") or 0.0),
                "fim_s": float(ed.get("fim_s") or 0.0),
                "edicao_manual": bool(ed.get("manual")),
                "eh_fala": bool(c["clipe"].get("eh_fala")),
                "narracao": (c.get("narracao") or "")[:120],
                # duração REAL do clipe (só quando o editor pede ?durs=1) — pra posicionar as alças
                "clipe_dur": (montagem_mod._duracao(d / "clipes" / cl) if (com_dur and clipe_ok) else 0.0),
            })
        itens.append({"vid": vid, "titulo": rot.get("titulo") or vid,
                      "estado": rot.get("estado"), "cenas": cenas})
    return jsonify({"ok": True, "itens": itens, "vids": pedidos})


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
            nome, analise, tentativas = keyframes_mod.gerar_keyframe_validado(
                rot_, cena_, d_ / "keyframes", cancel_event=cancel_event, extra=extra)
            atual = ler_json(d_ / "roteiro.json")
            for c in atual["cenas"]:
                if c["n"] == n:
                    c["keyframe"].update({"arquivo": nome, "aprovado": True,
                                          "tentativas": int(c["keyframe"].get("tentativas") or 0) + tentativas})
                    c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                                  "erro": None, "lipsync_aplicado": False}
                    c["qualidade"] = {"estado": "aprovado", "etapa": "keyframe",
                                      "tentativa": tentativas, "motivos": [],
                                      "descartes": max(0, tentativas - 1), "analise": analise}
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


# ---------------------------------------------------------------- inserts (B-roll/motion)
@ugc.post("/api/insert/<produto>/<vid>/<int:n>")
def definir_insert(produto, vid, n):
    """Liga/desliga o insert e/ou grava a direção (conceito + prompts) da cena `n`."""
    dado = request.get_json(silent=True) or {}
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    if not next((c for c in rot["cenas"] if c["n"] == n), None):
        return _erro("Cena não encontrada.", 404)
    if "ativo" in dado:
        inserts_mod.definir_ativo(produto, vid, n, bool(dado.get("ativo")))
    if any(k in dado for k in ("conceito", "prompt_imagem", "prompt_movimento")):
        inserts_mod.definir_direcao(produto, vid, n,
                                     conceito=(dado.get("conceito") or "").strip(),
                                     prompt_imagem=(dado.get("prompt_imagem") or "").strip(),
                                     prompt_movimento=(dado.get("prompt_movimento") or "").strip())
    return jsonify({"ok": True})


@ugc.post("/api/gerar_insert_imagem/<produto>/<vid>/<int:n>")
def gerar_insert_imagem(produto, vid, n):
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    if not next((c for c in rot["cenas"] if c["n"] == n), None):
        return _erro("Cena não encontrada.", 404)

    def _job(produto_, vid_, cancel_event=None):
        status = JobStatus(video_dir(produto_, vid_) / "status.json", "insert_imagem", 1)
        try:
            status.comecou(f"insert_cena_{n:02d}")
            inserts_mod.gerar_imagem_insert(produto_, vid_, n)
            status.terminou(f"insert_cena_{n:02d}")
        except Exception as e:  # noqa: BLE001
            status.terminou(f"insert_cena_{n:02d}", erro=str(e))
        finally:
            status.fim()

    if not _rodar_em_thread(_chave(produto, vid), _job, produto, vid):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
    return jsonify({"ok": True})


@ugc.post("/api/aprovar_insert/<produto>/<vid>/<int:n>")
def aprovar_insert(produto, vid, n):
    dado = request.get_json(silent=True) or {}
    aprovado = bool(dado.get("aprovado", True))
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    if not next((c for c in rot["cenas"] if c["n"] == n), None):
        return _erro("Cena não encontrada.", 404)
    inserts_mod.aprovar_imagem_insert(produto, vid, n, aprovado)
    return jsonify({"ok": True})


@ugc.post("/api/gerar_insert_clipe/<produto>/<vid>/<int:n>")
def gerar_insert_clipe(produto, vid, n):
    dado = request.get_json(silent=True) or {}
    d = video_dir(produto, vid)
    rot = ler_json(d / "roteiro.json")
    cena = next((c for c in rot["cenas"] if c["n"] == n), None)
    if not cena:
        return _erro("Cena não encontrada.", 404)
    if not (cena.get("insert") or {}).get("imagem", {}).get("aprovado"):
        return _erro("Aprove a imagem do insert antes de animar.")
    if JobStatus.em_andamento(d / "status.json"):
        return _erro("Já existe um job em andamento para este vídeo.", 409)

    def _job(produto_, vid_, cancel_event=None):
        status = JobStatus(video_dir(produto_, vid_) / "status.json", "insert_clipe", 1)
        try:
            status.comecou(f"insert_cena_{n:02d}")
            inserts_mod.gerar_clipe_insert(produto_, vid_, n,
                                           duration_s=int(dado.get("duration_s") or 5),
                                           model=dado.get("modelo") or "veo_fast",
                                           cancel_event=cancel_event)
            status.terminou(f"insert_cena_{n:02d}")
        except Exception as e:  # noqa: BLE001
            status.terminou(f"insert_cena_{n:02d}", erro=str(e))
        finally:
            status.fim()

    if not _rodar_em_thread(_chave(produto, vid), _job, produto, vid):
        return _erro("Já existe um job em andamento para este vídeo.", 409)
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
    reprovados = [c["n"] for c in pendentes if not c["keyframe"].get("aprovado")]
    if reprovados:
        return _erro(f"Keyframes ainda não aprovados pelo controle de qualidade: {reprovados}.")
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
    protegidos = []
    for c in rot.get("cenas") or []:
        x = por_n.get(int(c["n"]))
        if not x:
            continue
        inicio = max(0.0, float(x.get("inicio_s") or 0.0))
        fim = max(0.0, float(x.get("fim_s") or 0.0))
        detalhe = (c.get("clipe") or {}).get("transcricao_detalhada")
        fim, palavra = qualidade_mod.proteger_fim_de_palavra(fim, detalhe)
        if palavra:
            protegidos.append({"n": c["n"], "palavra": palavra, "fim_s": fim})
        if fim and fim <= inicio + 0.10:
            return _erro(f"Corte invalido na cena {c['n']}: o fim precisa ser maior que o inicio.", 400)
        # manual=True: o usuário ajustou na timeline -> o auto-trim NUNCA sobrescreve isto.
        c["edicao"] = {"inicio_s": inicio, "fim_s": fim, "remover": bool(x.get("remover")),
                       "manual": True, "fim_protegido": bool(palavra)}
    atomic_write_json(d / "roteiro.json", rot)
    return jsonify({"ok": True, "cortes_protegidos": protegidos})


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
        ins = c.get("insert") or {}
        ins_img = (ins.get("imagem") or {}).get("arquivo")
        ins_clipe = (ins.get("clipe") or {}).get("arquivo")
        cenas.append({
            "n": c["n"], "tipo": c["tipo"], "narracao": c["narracao"],
            "instrucao_clipe": c.get("instrucao_clipe") or "",
            "prompt_keyframe": c["prompt_keyframe"], "prompt_movimento": c["prompt_movimento"],
            "keyframe": {**c["keyframe"],
                         "url": f"/ugc/media/{produto}/{vid}/keyframes/{kf}?t={_mtime(d / 'keyframes' / kf)}" if kf else None},
            "clipe": {**c["clipe"],
                      "url": f"/ugc/media/{produto}/{vid}/clipes/{cl}?t={_mtime(d / 'clipes' / cl)}" if cl else None},
            "audio": c.get("audio") or {},
            "qualidade": c.get("qualidade") or {"estado": "pendente"},
            "descartados": _descartes_cena(d, produto, vid, int(c["n"])),
            "edicao": c.get("edicao") or {"inicio_s": 0, "fim_s": 0, "remover": False},
            # Insert (B-roll/motion) OPCIONAL desta cena — ver app/pipeline/inserts.py.
            "insert": {
                "ativo": bool(ins.get("ativo")),
                "conceito": ins.get("conceito") or "",
                "prompt_imagem": ins.get("prompt_imagem") or "",
                "prompt_movimento": ins.get("prompt_movimento") or "",
                "imagem": {**(ins.get("imagem") or {}),
                          "url": (f"/ugc/media/{produto}/{vid}/keyframes/{ins_img}?t={_mtime(d / 'keyframes' / ins_img)}"
                                  if ins_img else None)},
                "clipe": {**(ins.get("clipe") or {}),
                         "url": (f"/ugc/media/{produto}/{vid}/clipes/{ins_clipe}?t={_mtime(d / 'clipes' / ins_clipe)}"
                                 if ins_clipe else None)},
            },
        })
    final = d / "final" / "video.mp4"
    bruto = d / "final" / "video-bruto.mp4"
    ajustado = d / "final" / "video-ajustado.mp4"
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
                    "bruto_url": f"/ugc/media/{produto}/{vid}/final/video-bruto.mp4?t={_mtime(bruto)}" if bruto.exists() else None,
                    "ajustado_url": f"/ugc/media/{produto}/{vid}/final/video-ajustado.mp4?t={_mtime(ajustado)}" if ajustado.exists() else None,
                    "final_url": f"/ugc/media/{produto}/{vid}/final/video.mp4?t={_mtime(final)}"
                    if final.exists() and rot.get("estado") == "montado" else None})


@ugc.get("/media/<produto>/<vid>/<path:arquivo>")
def media(produto, vid, arquivo):
    d = video_dir(produto, vid)
    alvo = safe_descendant(d, arquivo, suffixes={".png", ".jpg", ".mp4", ".wav", ".ass"})
    return send_from_directory(alvo.parent, alvo.name)
