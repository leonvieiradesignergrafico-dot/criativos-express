#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Worker de auto-cadastro — 1 cliente.

Fluxo (Fase 1):
  1. carrega o cliente de clients/<slug>/contexto.md (act_id(s), business_id, elegibilidade)
  2. chama /api/meta/ads.php?act=...&key=<DEUROI_KEY> no Dashboard (que tem o token server-side)
  3. agrupa os anúncios por URL de página de destino canônica  => PRODUTO
  4. por produto: baixa a copy da página, baixa imagens (criativos + página),
     e prepara (NÃO roda) a transcrição de vídeos via faster-whisper
  5. grava rascunho em products/<slug>/<produto>/ (config.md + contexto/ + referencia/ + REVISAR.md)
  6. devolve um resumo (dict) pro orquestrador agregar

REGRAS DURAS:
  - Read-only na Meta (via Dashboard) + escrita em arquivo local. Nunca sobe/edita/deleta na Meta.
  - Idempotente: só sobrescreve rascunhos AUTO (com marcador REVISAR.md). Produto manual => "conflito".
  - Custo zero: urllib/html.parser (stdlib), ffmpeg local (opcional), faster-whisper local (opcional).

Uso direto (1 cliente):
  python worker.py --cliente leon --dry-run
  python worker.py --cliente leon --fixture fake_ads.json   # testa o parser sem rede
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

# ---------------------------------------------------------------------------
# Localização das pastas do projeto
# worker.py está em  <repo>/Criativos Express/auto_cadastro/worker.py
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve()
CRIATIVOS_DIR = HERE.parents[1]                # <repo>/Criativos Express
REPO_ROOT = HERE.parents[2]                    # <repo> (Direct Response)
PRODUCTS_DIR = CRIATIVOS_DIR / "products"
CLIENTS_DIR = REPO_ROOT / "clients"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Marcador que identifica um rascunho gerado por esta ferramenta (idempotência).
AUTO_MARKER = "RASCUNHO AUTO-CADASTRO"

# Parâmetros de tracking a remover na canonicalização de URL.
TRACKING_PREFIXES = ("utm_", "_branch", "_hs", "mc_", "pk_")
TRACKING_KEYS = {
    "fbclid", "gclid", "gbraid", "wbraid", "msclkid", "ttclid", "twclid",
    "igshid", " scid", "yclid", "ref", "ref_src", "s_kwcid", "campaign_id",
    "ad_id", "adset_id", "hsa_acc", "hsa_cam", "hsa_grp", "hsa_ad",
}


# ===========================================================================
# .env / configuração
# ===========================================================================
def load_env() -> dict:
    """Lê DEUROI_BASE_URL / DEUROI_KEY de .env.local (runner) ou .env do Criativos.

    Ordem de procura (primeiro que existir vence por chave):
      1. orchestrator/runner/.env.local
      2. Criativos Express/.env.local
      3. Criativos Express/.env
    Variáveis de ambiente do processo têm prioridade sobre os arquivos.
    """
    env: dict = {}
    candidates = [
        REPO_ROOT / "orchestrator" / "runner" / ".env.local",
        CRIATIVOS_DIR / ".env.local",
        CRIATIVOS_DIR / ".env",
        REPO_ROOT / ".env.local",   # .env.local na raiz do workspace (Direct Response)
        REPO_ROOT / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            env.setdefault(k, v)   # não sobrescreve o que já foi lido de arquivo anterior
    # env do processo vence
    for k in ("DEUROI_BASE_URL", "DEUROI_KEY", "CRON_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def dashboard_config(env: dict) -> tuple[str, str]:
    base = (env.get("DEUROI_BASE_URL") or "https://deuroi.com.br").rstrip("/")
    key = env.get("DEUROI_KEY") or env.get("CRON_KEY") or ""
    return base, key


# ===========================================================================
# Cliente (clients/<slug>/contexto.md)
# ===========================================================================
def _extract_act_ids(text: str) -> list[str]:
    """Pega todos os act_id numéricos citados; ignora <TODO> e placeholders."""
    ids: list[str] = []
    for m in re.finditer(r"act_id[^\d<]*(\d{6,})", text):
        ids.append(m.group(1))
    # também captura "act_<digits>"
    for m in re.finditer(r"act_(\d{6,})", text):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    # dedup mantendo ordem
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def load_client(slug: str) -> dict:
    """Lê clients/<slug>/contexto.md e devolve o descritor do cliente.

    eligible = tem contexto real + ao menos 1 act_id numérico (não STUB <TODO>).
    """
    ctx = CLIENTS_DIR / slug / "contexto.md"
    info = {
        "slug": slug,
        "path": str(ctx),
        "act_ids": [],
        "business_id": "",
        "dashboard_client_id": "",
        "eligible": False,
        "reason": "",
    }
    if not ctx.is_file():
        info["reason"] = "sem contexto.md"
        return info
    text = ctx.read_text(encoding="utf-8", errors="ignore")

    info["act_ids"] = _extract_act_ids(text)
    mb = re.search(r"business_id[^\d<]*(\d{6,})", text)
    if mb:
        info["business_id"] = mb.group(1)
    mc = re.search(r"dashboard_client_id[^\n]*?[`:]\s*`?(\d+)`?", text)
    if mc:
        info["dashboard_client_id"] = mc.group(1)

    if not info["act_ids"]:
        info["reason"] = "STUB — sem act_id (<TODO>)"
    else:
        info["eligible"] = True
        info["reason"] = "ok"
    return info


def list_eligible_clients() -> list[dict]:
    """Varre clients/*/ e devolve os elegíveis (com act_id, fora _TEMPLATE/_office)."""
    out = []
    if not CLIENTS_DIR.is_dir():
        return out
    for d in sorted(CLIENTS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        info = load_client(d.name)
        out.append(info)
    return out


# ===========================================================================
# HTTP helpers (stdlib)
# ===========================================================================
def http_get(url: str, timeout: int = 60, as_json: bool = False,
             retries: int = 0, backoff: float = 2.0):
    """GET simples. Com retries>0, repete em erros TRANSIENTES (5xx, timeout, conexão)
    com backoff exponencial — cobre 502 Bad Gateway / read timeout do Dashboard sob carga."""
    attempt = 0
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                final_url = resp.geturl()
            if as_json:
                return json.loads(data.decode("utf-8", errors="replace")), final_url
            return data, final_url
        except urllib.error.HTTPError as e:
            transient = e.code in (429, 500, 502, 503, 504)
            if not transient or attempt >= retries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt >= retries:
                raise
        attempt += 1
        time.sleep(backoff * (2 ** (attempt - 1)))


def _fetch_ads_once(base_url: str, key: str, act_id: str,
                    status: str | None = None) -> dict:
    q = {"act": act_id, "key": key}
    if status:
        q["status"] = status
    url = f"{base_url}/api/meta/ads.php?" + urllib.parse.urlencode(q)
    # Contas grandes (centenas de anúncios) demoram / o gateway devolve 502 sob carga:
    # timeout generoso + retries com backoff.
    payload, _ = http_get(url, timeout=180, as_json=True, retries=4)
    return payload if isinstance(payload, dict) else {"ok": False, "error": str(payload)[:300]}


# Erro da Graph API (code 1) quando a conta tem anúncios demais (inclui o "cemitério"
# de arquivados/deletados) e o pedido único estoura o limite de dados do endpoint.
_META_OVERFLOW = "reduce the amount of data"
# Rate limit da Graph por ad-account (code 80004): precisa esperar e repetir.
_META_RATELIMIT = ("too many calls", "80004", "rate limit", "user request limit")


def _is_ratelimit(err: str) -> bool:
    el = (err or "").lower()
    return any(s in el for s in _META_RATELIMIT)


def fetch_ads(base_url: str, key: str, act_id: str,
              status: str | None = None) -> list[dict]:
    """Chama o endpoint de leitura do Dashboard e devolve a lista de anúncios.

    Contas MUITO grandes fazem a Graph API responder "Please reduce the amount of
    data..." (code 1) ao pedir tudo. Nesse caso, refazemos o pedido restrito a
    ACTIVE,PAUSED (o conjunto que interessa; exclui o cemitério de arquivados),
    que é exatamente o default recomendado no PLANO para contas grandes.
    """
    def _call(st):
        # Retry no NÍVEL DO PAYLOAD para rate limit (code 80004): o endpoint responde
        # HTTP 200 com ok:false, então o retry do http_get não pega. Espera crescente.
        # Também captura o 502/timeout do gateway (http_get RAISE) como falha, para o
        # chamador poder cair no fallback ACTIVE,PAUSED (pedido bem mais leve).
        waits = [20, 45, 90, 150]
        i = 0
        while True:
            try:
                p = _fetch_ads_once(base_url, key, act_id, st)
            except Exception as e:  # noqa: BLE001 — 502/timeout do gateway sob carga
                p = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if p.get("ok") or not _is_ratelimit(str(p.get("error") or p)) or i >= len(waits):
                return p
            time.sleep(waits[i]); i += 1

    payload = _call(status)
    if payload.get("ok"):
        return payload.get("ads", [])

    err = str(payload.get("error") or payload)
    # Conta gigante: o pedido "tudo" estoura (overflow code 1) OU derruba o gateway
    # (502/timeout) antes de responder. Em ambos os casos, refaz restrito a
    # ACTIVE,PAUSED — conjunto que interessa e request bem mais leve.
    heavy = (_META_OVERFLOW.lower() in err.lower()
             or "502" in err or "timed out" in err.lower() or "timeout" in err.lower())
    if not status and heavy:
        payload = _call("ACTIVE,PAUSED")
        if not payload.get("ok"):
            raise RuntimeError(
                "endpoint /api/meta/ads falhou mesmo com status=ACTIVE,PAUSED: "
                f"{str(payload.get('error') or payload)[:300]}")
        return payload.get("ads", [])
    raise RuntimeError(f"endpoint /api/meta/ads falhou: {err[:300]}")


def fetch_accounts(base_url: str, key: str) -> list[dict]:
    """Descobre clientes ATIVOS + suas contas de anúncio via /api/meta/accounts.

    Fonte = banco do Dashboard (funnels.meta_ad_account_id por cliente) — o MESMO
    mapa que alimenta as métricas de todos os clientes. Não depende de contexto.md.
    Retorna [{id, slug, nome, type, act_ids:[...], business_id}]. RuntimeError se falhar.
    """
    url = f"{base_url}/api/meta/accounts.php?" + urllib.parse.urlencode({"key": key})
    payload, _ = http_get(url, timeout=120, as_json=True, retries=3)
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError(f"endpoint /api/meta/accounts falhou: {str(payload)[:300]}")
    return payload.get("clients", [])


def fetch_video_source(base_url: str, key: str, video_id: str) -> dict:
    """Resolve video_id -> {source, thumbnails, ...} via /api/meta/video.php.

    O worker LOCAL não tem token Meta: quem resolve é o Dashboard (server-side).
    A URL `source` é assinada e TEMPORÁRIA — baixar imediatamente.
    Levanta RuntimeError se a rota devolver ok:false ou erro HTTP.
    """
    url = f"{base_url}/api/meta/video.php?" + urllib.parse.urlencode(
        {"id": video_id, "key": key})
    # O gateway do Dashboard responde 502/timeout sob carga ao resolver o source
    # na Graph API: retries com backoff cobrem o transitório (mesma robustez do ads.php).
    payload, _ = http_get(url, timeout=120, as_json=True, retries=4)
    if not isinstance(payload, dict):
        raise RuntimeError("resposta inválida de /api/meta/video")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "video sem source")
    if not payload.get("source"):
        raise RuntimeError("source vazio")
    return payload


def download_file(url: str, dest: Path, timeout: int = 120,
                  max_bytes: int = 300 * 1024 * 1024) -> int:
    """Baixa um arquivo grande em streaming (chunks) pra `dest`. Retorna bytes.

    Levanta RuntimeError em HTTP != 200 ou se estourar `max_bytes` (proteção).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", 200)
        if status and int(status) != 200:
            raise RuntimeError(f"HTTP {status} ao baixar vídeo")
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise RuntimeError(f"vídeo excede o limite de {max_bytes} bytes")
                fh.write(chunk)
    return total


# ===========================================================================
# Canonicalização de URL + agrupamento
# ===========================================================================
def resolve_redirects(url: str, timeout: int = 20) -> str:
    """Segue redirects (encurtadores, l.facebook.com) até a URL final. Best-effort."""
    if not url:
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl()
    except Exception:
        return url


def canonical_url(url: str) -> str:
    """Normaliza uma URL pra servir de chave de agrupamento.

    - host lowercase, sem 'www.'
    - remove params de tracking (utm_*, fbclid, etc.)
    - remove fragment (#...)
    - path sem barra final
    Mantém query relevante (ex.: ?produto=x) ordenada.
    """
    if not url:
        return ""
    # l.facebook.com/l.php?u=<encoded> — desembrulha
    try:
        pr = urllib.parse.urlparse(url)
        if pr.netloc.endswith("facebook.com") and pr.path.startswith("/l.php"):
            qs = urllib.parse.parse_qs(pr.query)
            if "u" in qs:
                return canonical_url(qs["u"][0])
    except Exception:
        pass

    pr = urllib.parse.urlparse(url)
    host = (pr.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", pr.path or "")

    kept = []
    for k, v in urllib.parse.parse_qsl(pr.query, keep_blank_values=False):
        kl = k.lower()
        if kl in TRACKING_KEYS:
            continue
        if any(kl.startswith(p) for p in TRACKING_PREFIXES):
            continue
        kept.append((k, v))
    kept.sort()
    query = urllib.parse.urlencode(kept)

    canon = host + path
    if query:
        canon += "?" + query
    return canon.lower()


def slugify(text: str, fallback: str = "produto") -> str:
    text = (text or "").strip().lower()
    # transliteração básica de acentos comuns pt-br
    trans = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
    text = text.translate(trans)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or fallback


def product_slug_from_url(canon: str) -> str:
    """Deriva um slug do produto a partir do path/host da URL canônica."""
    if not canon:
        return "sem-pagina"
    pr = urllib.parse.urlparse("http://" + canon if "://" not in canon else canon)
    parts = [p for p in (pr.path or "").split("/") if p]
    if parts:
        return slugify(parts[-1])
    # sem path => usa o domínio (sem TLD)
    host = pr.netloc or canon.split("/")[0]
    return slugify(host.split(".")[0])


def group_ads_by_product(ads: list[dict], follow_redirects: bool = False) -> dict:
    """Agrupa anúncios por URL de destino canônica.

    Retorna { canon_url: {"slug","urls":set,"ads":[...] } }.
    Anúncios sem link vão pro bucket especial "" (=> sem-pagina).
    """
    groups: dict[str, dict] = {}
    redirect_cache: dict[str, str] = {}
    for ad in ads:
        raw = (ad.get("link") or "").strip()
        resolved = raw
        if raw and follow_redirects:
            resolved = redirect_cache.get(raw)
            if resolved is None:
                resolved = resolve_redirects(raw)
                redirect_cache[raw] = resolved
        canon = canonical_url(resolved)
        g = groups.setdefault(canon, {
            "canon": canon,
            "slug": product_slug_from_url(canon) if canon else "sem-pagina",
            "urls": set(),
            "ads": [],
        })
        if raw:
            g["urls"].add(raw)
        if resolved and resolved != raw:
            g["urls"].add(resolved)
        g["ads"].append(ad)
    return groups


# ===========================================================================
# Extração de copy da página (html.parser, stdlib)
# ===========================================================================
class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "section", "h1", "h2", "h3", "h4", "li", "br", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []
        self.title = ""
        self.h1 = ""
        self.og_image = ""
        self.images: list[str] = []
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self._in_h1 = True
        a = dict(attrs)
        if tag == "img":
            src = a.get("src") or a.get("data-src") or ""
            if src:
                self.images.append(src)
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop == "og:image" and a.get("content"):
                self.og_image = a["content"]

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag == "h1":
            self._in_h1 = False
        if tag in self.BLOCK:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        if self._in_h1 and not self.h1:
            self.h1 = text
        self.chunks.append(text)

    def get_text(self) -> str:
        raw = " ".join(self.chunks)
        # normaliza espaços mas preserva quebras de bloco
        lines = [re.sub(r"[ \t]+", " ", ln).strip()
                 for ln in re.sub(r"\s*\n\s*", "\n", raw).split("\n")]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)


def extract_page(url: str, timeout: int = 30) -> dict:
    """Baixa a página e extrai texto + imagens. Best-effort (retorna erro no dict)."""
    result = {"url": url, "final_url": url, "title": "", "h1": "",
              "text": "", "images": [], "og_image": "", "error": ""}
    try:
        data, final_url = http_get(url, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"download falhou: {e}"
        return result
    result["final_url"] = final_url
    try:
        html = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        html = data.decode("latin-1", errors="replace")
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"parse falhou: {e}"
    result["title"] = p.title
    result["h1"] = p.h1
    result["text"] = p.get_text()
    result["og_image"] = urllib.parse.urljoin(final_url, p.og_image) if p.og_image else ""
    # resolve imagens relativas -> absolutas, dedup
    seen = set()
    for src in p.images:
        absu = urllib.parse.urljoin(final_url, src)
        if absu.startswith("http") and absu not in seen:
            seen.add(absu)
            result["images"].append(absu)
    return result


# ===========================================================================
# Download de imagens (com filtro de tamanho mínimo, sem Pillow)
# ===========================================================================
IMG_MIN_BYTES = 8 * 1024   # ignora ícones/pixels/logos pequenos


def download_image(url: str, dest: Path, min_bytes: int = IMG_MIN_BYTES) -> bool:
    try:
        data, _ = http_get(url, timeout=30)
    except Exception:  # noqa: BLE001
        return False
    if len(data) < min_bytes:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def download_creatives(ads: list[dict], dest_dir: Path, opts: dict, *,
                       want_images: bool = True, want_videos: bool = False,
                       img_prefix: str = "ref-anuncio", vid_prefix: str = "ref-video",
                       dedup: bool = True) -> tuple[list[dict], int, int]:
    """Baixa os criativos (imagens e/ou vídeos) de uma lista de anúncios para `dest_dir`.

    REUTILIZÁVEL: usa exatamente as MESMAS fontes read-only do fluxo normal
    (creative.image_url/thumbnail_url no CDN da Meta + /api/meta/video.php do
    Dashboard para resolver video_id), mas com DESTINO LIVRE. Isso permite baixar
    para `referencia/` (fluxo padrão) OU para `referencia_estilo/` (referência de
    ESTILO) sem duplicar a lógica. NUNCA escreve/edita/deleta na Meta.

    - Imagens: prefere creative.image_url; cai para thumbnail_url. 1 por anúncio.
    - Vídeos: resolve creative.video_id via fetch_video_source e baixa o source
      (URL assinada temporária) com download_file. Só se `want_videos=True` e
      houver base_url+key em `opts`.
    - dedup: não baixa o mesmo image_url / video_id duas vezes.
    - Idempotente: se o arquivo de destino já existe (>0 bytes), conta e não rebaixa.

    Retorna (fontes, n_imagens, n_videos). Cada item de `fontes` descreve a origem
    (mesma convenção do _fontes.json do fluxo normal), incluindo erros de vídeo.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    fontes: list[dict] = []
    n_img = n_vid = 0
    img_idx = vid_idx = 0
    seen_img: set[str] = set()
    seen_vid: set[str] = set()
    base = opts.get("base_url")
    key = opts.get("key")
    for a in ads:
        cr = a.get("creative", {}) or {}
        if want_images:
            for field in ("image_url", "thumbnail_url"):
                u = cr.get(field)
                if not u:
                    continue
                if dedup and u in seen_img:
                    break
                seen_img.add(u)
                img_idx += 1
                dest = dest_dir / f"{img_prefix}-{img_idx:02d}.png"
                if (dest.is_file() and dest.stat().st_size > 0) or download_image(u, dest):
                    n_img += 1
                    fontes.append({"file": dest.name, "from": "anuncio",
                                   "ad_id": a.get("id"), "field": field, "url": u})
                break  # 1 imagem por anúncio (image_url ou thumbnail)
        if want_videos and base and key:
            vid = cr.get("video_id")
            if not vid or (dedup and vid in seen_vid):
                continue
            seen_vid.add(vid)
            vid_idx += 1
            dest = dest_dir / f"{vid_prefix}-{vid_idx:02d}.mp4"
            if dest.is_file() and dest.stat().st_size > 0:
                n_vid += 1
                fontes.append({"file": dest.name, "from": "anuncio-video",
                               "ad_id": a.get("id"), "field": "video_id", "video_id": vid})
                continue
            try:
                meta = fetch_video_source(base, key, vid)
                download_file(meta["source"], dest)
                n_vid += 1
                fontes.append({"file": dest.name, "from": "anuncio-video",
                               "ad_id": a.get("id"), "field": "video_id", "video_id": vid})
            except Exception as e:  # noqa: BLE001 — source expirado/403/vídeo indisponível
                dest.unlink(missing_ok=True)
                fontes.append({"file": None, "from": "anuncio-video",
                               "ad_id": a.get("id"), "video_id": vid,
                               "error": f"{type(e).__name__}: {e}"})
    return fontes, n_img, n_vid


# ===========================================================================
# Transcrição (faster-whisper) — PREPARADA, não roda em dry-run
# ===========================================================================
def transcrever(audio_or_video_path: str, model_size: str = "small",
                language: str = "pt") -> str:
    """Transcreve um arquivo de áudio/vídeo com faster-whisper (CPU, int8).

    NÃO é chamada em --dry-run. Protegida por try/except: se faster-whisper ou
    o modelo faltar, devolve string vazia + registra o motivo (nunca derruba o worker).
    Requer o áudio já extraído (wav 16k mono) OU um arquivo que o ffmpeg do
    faster-whisper consiga abrir.
    """
    try:
        from faster_whisper import WhisperModel  # import tardio (custo-zero se não usar)
    except Exception as e:  # noqa: BLE001
        return f"[transcrição indisponível: faster-whisper não importou: {e}]"
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(audio_or_video_path, language=language)
        return " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:  # noqa: BLE001
        return f"[transcrição falhou: {e}]"


# ===========================================================================
# Escrita do rascunho do produto
# ===========================================================================
def _is_auto_draft(product_dir: Path) -> bool:
    """True se a pasta é um rascunho gerado por esta ferramenta (tem o marcador)."""
    revisar = product_dir / "REVISAR.md"
    if revisar.is_file():
        return AUTO_MARKER in revisar.read_text(encoding="utf-8", errors="ignore")
    cfg = product_dir / "config.md"
    if cfg.is_file():
        return AUTO_MARKER in cfg.read_text(encoding="utf-8", errors="ignore")
    return False


def build_config_md(slug: str, group: dict, page: dict, gen_date: str) -> str:
    """Monta um config.md no formato do _TEMPLATE, com o que dá pra inferir e
    'Não informado' / '⏳ CONFIRMAR:' onde o dado é incerto (igual ao Bolo Iohanna)."""
    ads = group["ads"]
    nome = page.get("h1") or page.get("title") or slug.replace("-", " ").title()
    ctas = sorted({a.get("copy", {}).get("cta", "") for a in ads if a.get("copy", {}).get("cta")})
    headlines = [a.get("copy", {}).get("headline", "") for a in ads if a.get("copy", {}).get("headline")]
    kinds = sorted({a.get("creative", {}).get("object_type", "") for a in ads})
    urls = "; ".join(sorted(group.get("urls", []))) or "Não informado"

    lines = [
        f"# Configuração do produto — {nome}",
        "",
        f"> {AUTO_MARKER} — pendente de revisão do Leon (gerado em {gen_date}).",
        "> Preenchido automaticamente a partir dos anúncios + página + (transcrição pendente).",
        "> Revise cada campo antes de usar em copy/criativo. `⏳ CONFIRMAR:` = incerto.",
        "",
        "## Produto",
        f"- **Nome:** {nome}",
        "- **Tipo:** ⏳ CONFIRMAR: fisico | digital (inferir pela natureza da página)",
        f"- **O que é:** ⏳ CONFIRMAR: (resumir da página de vendas — ver contexto/pagina-vendas.txt)",
        "- **Diferenciais:** ⏳ CONFIRMAR: (extrair da página)",
        "- **Preço / oferta:** ⏳ CONFIRMAR: (extrair da página / checkout)",
        "",
        "## Público-alvo",
        "- **Quem é:** ⏳ CONFIRMAR:",
        "- **Nível de consciência:** ⏳ CONFIRMAR:",
        "- **Objeções comuns:** ⏳ CONFIRMAR:",
        "",
        "## Tom de voz / regras de copy",
        "- **Tom:** ⏳ CONFIRMAR: (inferir dos anúncios — ver contexto/anuncios.json)",
        f"- **Gatilhos preferidos:** ⏳ CONFIRMAR:",
        "- **Proibições de copy:** Não informado",
        "",
        "## Regras visuais OBRIGATÓRIAS",
        "- **Cores da marca (produto/cena):** ⏳ CONFIRMAR: (ver referencia/)",
        "- **Cor de destaque / cor do botão de CTA:** Não informado",
        "- **Estilo das imagens:** ⏳ CONFIRMAR: (ver referencia/ — imagens reais dos anúncios/página)",
        "- **Sempre incluir:** ⏳ CONFIRMAR:",
        "- **Formato padrão:** 1024x1024 feed",
        "",
        "## Proibições visuais",
        "- Não inventar rótulo/texto diferente do real.",
        "- Não distorcer proporções do produto.",
        "- Deixar os dois cantos superiores limpos para o logo entrar na pós.",
        "",
        "## Observações livres (auto-cadastro)",
        f"- **Anúncios no grupo:** {len(ads)}  |  **Tipos de criativo:** {', '.join(k for k in kinds if k) or 'n/d'}",
        f"- **CTAs observados:** {', '.join(ctas) or 'n/d'}",
        f"- **URL(s) de destino:** {urls}",
    ]
    if headlines:
        lines.append(f"- **Headlines dos anúncios:** {' | '.join(headlines[:8])}")
    if page.get("error"):
        lines.append(f"- ⚠️ Página não pôde ser lida automaticamente: {page['error']} "
                     "(usar fallback Chrome assistido — ver PENDENCIAS-LEON.md).")
    return "\n".join(lines) + "\n"


def build_revisar_md(slug: str, group: dict, page: dict, flags: list[str],
                     gen_date: str) -> str:
    ads = group["ads"]
    lines = [
        f"# {AUTO_MARKER} — {slug}",
        "",
        f"Gerado em **{gen_date}**. Este produto é um **rascunho automático** montado a",
        "partir dos anúncios existentes na Meta. **Revise antes de gerar qualquer copy/criativo.**",
        "",
        "## Checklist de revisão",
        "- [ ] Nome comercial do produto está correto",
        "- [ ] Tipo (fisico/digital) confirmado",
        "- [ ] Preço / oferta conferido no checkout real",
        "- [ ] Copy da página (`contexto/pagina-vendas.txt`) faz sentido / não veio truncada",
        "- [ ] Transcrições de vídeo geradas e revisadas (veja abaixo)",
        "- [ ] Imagens de `referencia/` são realmente do produto (conferir `_fontes.json`)",
        "- [ ] O agrupamento (anúncios -> este produto) está correto",
        "",
        "## Sinais / flags",
    ]
    for f in (flags or ["nenhum"]):
        lines.append(f"- {f}")
    lines += [
        "",
        "## Origem",
        f"- Anúncios agrupados: **{len(ads)}**",
        f"- URL(s): {', '.join(sorted(group.get('urls', []))) or 'sem página'}",
    ]
    return "\n".join(lines) + "\n"


def write_draft(client_slug: str, group: dict, page: dict, opts: dict) -> dict:
    """Escreve (ou atualiza) o rascunho do produto. Idempotente.

    Retorna um mini-relatório do que aconteceu com este produto.
    """
    gen_date = opts.get("gen_date", date.today().isoformat())
    slug = group["slug"]
    ads = group["ads"]
    report = {
        "slug": slug,
        "ads": len(ads),
        "action": "",       # created | updated | conflict-skip
        "flags": [],
        "images_saved": 0,
        "videos": 0,
    }
    flags: list[str] = []
    if not page.get("final_url") and not page.get("url"):
        flags.append("sem-pagina (anúncios sem link de destino)")
    if page.get("error"):
        flags.append(f"pagina-nao-lida: {page['error']}")
    if len(ads) == 1:
        flags.append("confiança baixa (1 anúncio só no grupo)")
    if all(a.get("status") not in ("ACTIVE",) and a.get("effective_status") not in ("ACTIVE",)
           for a in ads):
        flags.append("so_pausados (nenhum anúncio ativo no grupo)")

    product_dir = PRODUCTS_DIR / client_slug / slug

    # Produto MANUAL legado no topo (products/<slug>, esquema antigo) com o mesmo
    # slug: não é o mesmo caminho (não sobrescreve), mas avisa pro Leon reconciliar.
    legacy = PRODUCTS_DIR / slug
    if legacy.is_dir() and legacy != product_dir and not _is_auto_draft(legacy):
        flags.append(f"⚠️ existe produto manual legado em products/{slug}/ — reconciliar")

    # --- idempotência / conflito ---
    if product_dir.exists():
        if not _is_auto_draft(product_dir):
            report["action"] = "conflict-skip"
            flags.append("CONFLITO: produto já existe (feito à mão) — NÃO sobrescrito")
            report["flags"] = flags
            return report
        report["action"] = "updated"
    else:
        report["action"] = "created"

    if opts.get("write") is False:
        # modo --no-write (só planeja)
        report["flags"] = flags
        return report

    # ref_subdir permite direcionar os criativos para "referencia" (padrão) ou
    # "referencia_estilo" sem mexer no resto do fluxo.
    ref_subdir = opts.get("ref_subdir", "referencia")
    (product_dir / "contexto").mkdir(parents=True, exist_ok=True)
    (product_dir / ref_subdir).mkdir(parents=True, exist_ok=True)
    ctx = product_dir / "contexto"
    ref = product_dir / ref_subdir

    # --- contexto/anuncios.json (sempre) ---
    anuncios = [{
        "id": a.get("id"),
        "name": a.get("name"),
        "status": a.get("status"),
        "effective_status": a.get("effective_status"),
        "campaign_name": a.get("campaign_name"),
        "adset_id": a.get("adset_id"),
        "copy": a.get("copy"),
        "cta": a.get("copy", {}).get("cta"),
        "link": a.get("link"),
        "creative": a.get("creative"),
    } for a in ads]
    (ctx / "anuncios.json").write_text(
        json.dumps(anuncios, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- contexto/pagina-vendas.txt ---
    if page.get("text"):
        header = f"# {page.get('title') or slug}\n# fonte: {page.get('final_url','')}\n\n"
        (ctx / "pagina-vendas.txt").write_text(header + page["text"], encoding="utf-8")

    # --- imagens de referência (criativos + página) ---
    fontes = []
    if opts.get("download_images", True):
        idx = 0
        # dos criativos (image_url / thumbnail)
        for a in ads:
            cr = a.get("creative", {})
            for field in ("image_url", "thumbnail_url"):
                u = cr.get(field)
                if not u:
                    continue
                idx += 1
                dest = ref / f"ref-anuncio-{idx:02d}.png"
                if download_image(u, dest):
                    report["images_saved"] += 1
                    fontes.append({"file": dest.name, "from": "anuncio",
                                   "ad_id": a.get("id"), "field": field, "url": u})
                break  # 1 por anúncio (image ou thumb)
        # da página (og:image + hero)
        page_imgs = ([page["og_image"]] if page.get("og_image") else []) + page.get("images", [])
        for j, u in enumerate(page_imgs[:6], 1):
            dest = ref / f"ref-pagina-{j:02d}.png"
            if download_image(u, dest):
                report["images_saved"] += 1
                fontes.append({"file": dest.name, "from": "pagina", "url": u})
    else:
        flags.append("imagens não baixadas (--no-images / dry-run)")

    if fontes:
        (ref / "_fontes.json").write_text(
            json.dumps(fontes, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- transcrição de vídeos ---
    # video_id -> source (rota do Dashboard) -> download tmp -> faster-whisper -> .txt
    # Só roda com --transcribe. Em --dry-run: NÃO baixa nem transcreve (só marca).
    video_ads = [a for a in ads if a.get("creative", {}).get("video_id")]
    report["videos"] = len(video_ads)
    if video_ads:
        tdir = ctx / "transcricao"
        tdir.mkdir(exist_ok=True)
        if opts.get("transcribe", False):
            ok_count, pend_count = 0, 0
            for n, a in enumerate(video_ads, 1):
                vid = a.get("creative", {}).get("video_id", "")
                out_txt = tdir / f"transcricao-{n:02d}.txt"
                pend = tdir / f"transcricao-{n:02d}_PENDENTE.txt"
                if out_txt.is_file() and out_txt.stat().st_size > 0:
                    ok_count += 1
                    continue  # idempotente: já transcrito, não re-baixa
                tmp_mp4 = tdir / f"_tmp-video-{n:02d}.mp4"
                try:
                    meta = fetch_video_source(opts["base_url"], opts["key"], vid)
                    download_file(meta["source"], tmp_mp4)
                    texto = transcrever(str(tmp_mp4),
                                        model_size=opts.get("whisper_model", "small"))
                    if not texto or texto.startswith("["):
                        # transcrição indisponível/falhou/sem_audio
                        pend.write_text(
                            f"video_id={vid}\nmotivo: {texto or 'transcrição vazia (sem_audio?)'}\n",
                            encoding="utf-8")
                        pend_count += 1
                    else:
                        header = (f"# transcrição do criativo de vídeo (ad {a.get('id')}, "
                                  f"video_id {vid})\n\n")
                        out_txt.write_text(header + texto + "\n", encoding="utf-8")
                        pend.unlink(missing_ok=True)
                        ok_count += 1
                except Exception as e:  # noqa: BLE001
                    # source expirado/403, vídeo indisponível, rota fora do ar etc.
                    pend.write_text(f"video_id={vid}\nmotivo: {e}\n", encoding="utf-8")
                    pend_count += 1
                finally:
                    tmp_mp4.unlink(missing_ok=True)  # nunca deixa o vídeo, só o texto
            flags.append(f"{len(video_ads)} vídeo(s) — transcritos={ok_count}, pendentes={pend_count}")
        else:
            (tdir / "_PENDENTE.txt").write_text(
                f"{len(video_ads)} criativo(s) de vídeo neste produto.\n"
                "Transcrição NÃO executada (dry-run / sem --transcribe).\n"
                "Rodar depois: worker com --transcribe (baixa via /api/meta/video + faster-whisper).\n",
                encoding="utf-8")
            flags.append(f"{len(video_ads)} vídeo(s) — transcrição pendente (dry-run)")

    # --- config.md + REVISAR.md ---
    (product_dir / "config.md").write_text(
        build_config_md(slug, group, page, gen_date), encoding="utf-8")
    (product_dir / "REVISAR.md").write_text(
        build_revisar_md(slug, group, page, flags, gen_date), encoding="utf-8")

    report["flags"] = flags
    return report


# ===========================================================================
# Worker principal (1 cliente)
# ===========================================================================
def run_client(slug: str, opts: dict) -> dict:
    """Processa 1 cliente ponta a ponta. Devolve o resumo pro orquestrador."""
    gen_date = opts.get("gen_date", date.today().isoformat())
    summary = {
        "cliente": slug,
        "gen_date": gen_date,
        "ok": False,
        "eligible": False,
        "act_ids": [],
        "total_ads": 0,
        "products": [],
        "conflicts": [],
        "sem_pagina": 0,
        "errors": [],
    }

    # act_ids: prioriza os INJETADOS pelo orquestrador (descoberta via banco no
    # endpoint /api/meta/accounts). Sem eles, cai no fallback contexto.md.
    injected = opts.get("act_ids")
    if injected:
        act_ids = list(injected)
        summary["eligible"] = True
        summary["act_ids"] = act_ids
        summary["source"] = opts.get("act_source", "banco")
    else:
        client = load_client(slug)
        summary["eligible"] = client["eligible"]
        summary["act_ids"] = client["act_ids"]
        summary["source"] = "contexto.md"
        if not client["eligible"]:
            summary["errors"].append(f"cliente inelegível: {client['reason']}")
            return summary
        act_ids = client["act_ids"]

    # 1) coletar anúncios de todas as contas do cliente
    ads: list[dict] = []
    fixture = opts.get("fixture")
    if fixture:
        ads = json.loads(Path(fixture).read_text(encoding="utf-8"))
        if isinstance(ads, dict):
            ads = ads.get("ads", [])
    else:
        base, key = opts["base_url"], opts["key"]
        if not key:
            summary["errors"].append("DEUROI_KEY/CRON_KEY ausente — não dá pra chamar o endpoint")
            return summary
        for act in act_ids:
            try:
                got = fetch_ads(base, key, act, status=opts.get("status"))
                ads.extend(got)
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"act {act}: {e}")
    summary["total_ads"] = len(ads)

    if not ads:
        summary["ok"] = len(summary["errors"]) == 0
        return summary

    # 2) agrupar por produto (URL canônica)
    groups = group_ads_by_product(ads, follow_redirects=opts.get("follow_redirects", False))

    # 3) por produto: página + imagens + rascunho
    for canon, group in groups.items():
        page = {"url": "", "final_url": "", "text": "", "images": [],
                "og_image": "", "title": "", "h1": "", "error": ""}
        target = ""
        if group.get("urls"):
            target = sorted(group["urls"])[0]
        if canon and target and opts.get("fetch_page", True):
            page = extract_page(target)
        elif canon:
            page["url"] = target
            page["final_url"] = target

        rep = write_draft(slug, group, page, opts)
        if rep["action"] == "conflict-skip":
            summary["conflicts"].append(rep["slug"])
        if rep["slug"] == "sem-pagina":
            summary["sem_pagina"] = rep["ads"]
        summary["products"].append(rep)

    summary["ok"] = True
    return summary


# ===========================================================================
# CLI (1 cliente)
# ===========================================================================
def build_opts_from_args(args) -> dict:
    env = load_env()
    base, key = dashboard_config(env)
    dry = args.dry_run
    return {
        "base_url": base,
        "key": key,
        "status": args.status,
        "fixture": args.fixture,
        "dry_run": dry,
        # dry-run: baixa página/imagens mas NÃO transcreve; sem gastar CPU pesada.
        "fetch_page": not args.no_page,
        "download_images": (not args.no_images) and (not args.fixture),
        "transcribe": args.transcribe and not dry,
        "follow_redirects": args.follow_redirects and not args.fixture,
        "write": not args.no_write,
        "gen_date": date.today().isoformat(),
    }


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Auto-cadastro — worker de 1 cliente")
    ap.add_argument("--cliente", required=True, help="slug do cliente (clients/<slug>/)")
    ap.add_argument("--dry-run", action="store_true",
                    help="não transcreve (só prepara). Ainda baixa página/imagens salvo --no-page/--no-images.")
    ap.add_argument("--status", default=None, help="filtro Meta effective_status, ex.: ACTIVE ou ACTIVE,PAUSED")
    ap.add_argument("--fixture", default=None, help="JSON local de anúncios (testa o parser sem rede)")
    ap.add_argument("--transcribe", action="store_true", help="roda faster-whisper (ignorado em --dry-run)")
    ap.add_argument("--follow-redirects", action="store_true", help="resolve encurtadores (rede extra)")
    ap.add_argument("--no-page", action="store_true", help="não baixa a página de vendas")
    ap.add_argument("--no-images", action="store_true", help="não baixa imagens")
    ap.add_argument("--no-write", action="store_true", help="planeja mas não escreve arquivos")
    ap.add_argument("--json", action="store_true", help="imprime o resumo em JSON")
    args = ap.parse_args(argv)

    opts = build_opts_from_args(args)
    summary = run_client(args.cliente, opts)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"cliente={summary['cliente']} elegível={summary['eligible']} "
              f"ads={summary['total_ads']} produtos={len(summary['products'])} "
              f"conflitos={len(summary['conflicts'])} erros={len(summary['errors'])}")
        for p in summary["products"]:
            print(f"  - {p['slug']}: {p['action']} (ads={p['ads']}, imgs={p['images_saved']}, "
                  f"videos={p['videos']}) {('; '.join(p['flags']) if p['flags'] else '')}")
        for e in summary["errors"]:
            print(f"  ! {e}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
