"""Primitives compartilhadas de segurança, persistência e jobs locais."""
from __future__ import annotations

import json
import os
import re
import unicodedata
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCTS = ROOT / "products"
# Vídeo UGC (fluxo separado do de imagem): escrita em videos/ e avatares/.
VIDEOS = ROOT / "videos"
AVATARES = ROOT / "avatares"
# Influenciadores REAIS (fotos enviadas pelo usuário) dos criativos estáticos.
INFLUENCIADORES = ROOT / "influenciadores"
_LOCKS_DIR = VIDEOS / ".locks"
_PRODUCT_RE = re.compile(r"^[^\\/]+$")


def carregar_config() -> dict:
    import tomllib
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def product_dir(name: str) -> Path:
    """Resolve um produto existente sem permitir traversal ou caminhos absolutos.

    Aceita dois formatos de id:
      - "Bolo Iohanna"        -> products/Bolo Iohanna/            (produto solto/legado)
      - "leon~pack-skills"    -> products/leon/pack-skills/         (produto agrupado por cliente)
    O '~' é o delimitador cliente~produto (URL-safe, não aparece em nome real). Nunca
    há '/' no id (rota/encodeURIComponent seguem intactos), a tradução p/ subpasta é feita aqui.
    """
    if not isinstance(name, str) or not name or name in {".", ".."} or not _PRODUCT_RE.fullmatch(name):
        raise ValueError("Nome de produto inválido.")
    if "~" in name:
        cliente, _, prod = name.partition("~")
        if not cliente or not prod or cliente in {".", ".."} or prod in {".", ".."}:
            raise ValueError("Nome de produto inválido.")
        candidate = (PRODUCTS / cliente / prod).resolve()
    else:
        candidate = (PRODUCTS / name).resolve()
    root = PRODUCTS.resolve()
    if root not in candidate.parents or not candidate.is_dir():
        raise ValueError("Produto não encontrado.")
    return candidate


def safe_child(parent: Path, name: str, *, suffix: str | None = None) -> Path:
    """Resolve um arquivo diretamente dentro de parent."""
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("Arquivo inválido.")
    candidate = (parent / name).resolve()
    if candidate.parent != parent.resolve():
        raise ValueError("Arquivo fora do diretório permitido.")
    if suffix and candidate.suffix.lower() != suffix.lower():
        raise ValueError("Extensão de arquivo inválida.")
    return candidate


def safe_descendant(parent: Path, name: str, *, suffix: str | None = None,
                    suffixes: set | None = None) -> Path:
    """Resolve caminho relativo dentro de parent, aceitando subpastas controladas.

    suffix: exige uma extensão específica. suffixes: aceita um conjunto de extensões
    (usado pelo fluxo de vídeo, que serve .png/.mp4/.wav/.ass da mesma pasta)."""
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("Caminho inválido.")
    candidate = (parent / name).resolve()
    root = parent.resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("Caminho fora do diretório permitido.")
    if suffix and candidate.suffix.lower() != suffix.lower():
        raise ValueError("Extensão de arquivo inválida.")
    if suffixes and candidate.suffix.lower() not in {s.lower() for s in suffixes}:
        raise ValueError("Extensão de arquivo inválida.")
    return candidate


def _nome_valido(name: str) -> bool:
    return (isinstance(name, str) and bool(name) and name not in {".", ".."}
            and bool(_PRODUCT_RE.fullmatch(name)) and not name.startswith("."))


def video_dir(produto: str, vid: str, *, create: bool = False) -> Path:
    """Resolve videos/<produto>/<vid> (escrita local do fluxo de vídeo UGC)."""
    product_dir(produto)  # valida que o produto existe
    if not _nome_valido(vid):
        raise ValueError("Id de vídeo inválido.")
    d = (VIDEOS / produto / vid).resolve()
    if VIDEOS.resolve() not in d.parents:
        raise ValueError("Caminho de vídeo inválido.")
    if create:
        d.mkdir(parents=True, exist_ok=True)
    elif not d.is_dir():
        raise ValueError("Vídeo não encontrado.")
    return d


def avatar_dir(nome: str, *, create: bool = False) -> Path:
    """Resolve avatares/<nome> (avatares reutilizáveis do fluxo de vídeo UGC)."""
    if not _nome_valido(nome):
        raise ValueError("Nome de avatar inválido.")
    d = (AVATARES / nome).resolve()
    if AVATARES.resolve() not in d.parents:
        raise ValueError("Caminho de avatar inválido.")
    if create:
        d.mkdir(parents=True, exist_ok=True)
    elif not d.is_dir():
        raise ValueError("Avatar não encontrado.")
    return d


def influencer_dir(nome: str, *, create: bool = False) -> Path:
    """Resolve influenciadores/<nome> (pessoas reais dos criativos estáticos)."""
    if not _nome_valido(nome):
        raise ValueError("Nome de influenciador inválido.")
    d = (INFLUENCIADORES / nome).resolve()
    if INFLUENCIADORES.resolve() not in d.parents:
        raise ValueError("Caminho de influenciador inválido.")
    if create:
        d.mkdir(parents=True, exist_ok=True)
    elif not d.is_dir():
        raise ValueError("Influenciador não encontrado.")
    return d


def pessoa_dir(nome: str, tipo: str = "avatar", *, create: bool = False) -> Path:
    """Resolve a pasta da PESSOA que aparece no vídeo: um avatar UGC genérico
    (avatares/) ou um influenciador real (influenciadores/). Mesma estrutura
    de pasta nos dois (perfil.md + referencia/)."""
    if tipo == "influenciador":
        return influencer_dir(nome, create=create)
    return avatar_dir(nome, create=create)


# Tolera o markdown do config.md, ex.: "- **Tipo:** digital" (o ':' vem colado ao '**').
_RE_TIPO_PRODUTO = re.compile(r"tipo[^:\n]*:[\W_]*(digital|f[íi]sico)", re.IGNORECASE)


def tipo_produto(produto: str) -> str:
    """Lê o campo '- **Tipo:** digital|fisico' do config.md do produto.
    Default 'fisico' (mantém todos os produtos físicos existentes intactos)."""
    cfg = product_dir(produto) / "config.md"
    if cfg.exists():
        texto = cfg.read_text(encoding="utf-8", errors="replace")
        # Alguns cadastros antigos mantêm o placeholder "fisico | digital" e
        # depois recebem um segundo campo explícito. Considere todos os campos
        # e dê prioridade ao valor explícito, em vez de parar no placeholder.
        campos = _RE_TIPO_PRODUTO.findall(texto)
        for bruto in reversed(campos):
            campo = "".join(c for c in unicodedata.normalize("NFKD", bruto.casefold())
                            if not unicodedata.combining(c))
            if "digital" in campo and "fisico" not in campo:
                return "digital"
            if "fisico" in campo and "digital" not in campo:
                return "fisico"
        contexto = unicodedata.normalize("NFKD", (produto + "\n" + texto).casefold())
        contexto = "".join(c for c in contexto if not unicodedata.combining(c))
        if any(p in contexto for p in ("plugin", "software", "curso", "ebook", "e-book", "aula", "download", "app", "plataforma", "online", "interface")):
            return "digital"
    return "fisico"


def ler_json(path: Path, default=None):
    try:
        # utf-8-sig tolera um BOM que ferramentas externas possam ter gravado.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(content, encoding="utf-8")
        # No Windows, um leitor de polling pode manter o destino aberto por
        # alguns milissegundos. Repetimos a troca atômica; nunca escrevemos
        # diretamente no arquivo final como fallback.
        ultimo_erro = None
        for tentativa in range(12):
            try:
                os.replace(temp, path)
                ultimo_erro = None
                break
            except PermissionError as exc:
                ultimo_erro = exc
                if tentativa == 11:
                    raise
                time.sleep(0.05 * (tentativa + 1))
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, value) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


class JobManager:
    """Locks e cancelamento únicos para todas as interfaces deste processo."""
    def __init__(self):
        self._locks: dict[str, _ProductLock] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._guard = threading.Lock()

    def lock(self, product: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(product, _ProductLock(product))

    def cancel(self, product: str) -> threading.Event:
        with self._guard:
            return self._cancels.setdefault(product, threading.Event())

    def new_id(self) -> str:
        return uuid.uuid4().hex


class _ProductLock:
    """Lock de processo + marcador atômico para as duas interfaces separadas."""
    def __init__(self, product: str):
        self._local = threading.Lock()
        self._product = product
        self._marker: Path | None = None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def acquire(self, blocking=True, timeout=-1):
        acquired = self._local.acquire(False) if not blocking else self._local.acquire(True, timeout)
        if not acquired:
            return False
        marker = product_dir(self._product) / "output" / ".generation.lock"
        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            while True:
                try:
                    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode("ascii"))
                    os.close(fd)
                    self._marker = marker
                    return True
                except FileExistsError:
                    try:
                        pid = int(marker.read_text(encoding="ascii").strip())
                    except (OSError, ValueError):
                        pid = -1
                    if self._pid_alive(pid):
                        self._local.release()
                        return False
                    marker.unlink(missing_ok=True)
        except Exception:
            self._local.release()
            raise

    def release(self):
        if self._marker is not None:
            self._marker.unlink(missing_ok=True)
            self._marker = None
        self._local.release()


JOBS = JobManager()


class _KeyLock:
    """Lock por chave arbitrária (ex.: 'produto/video_id'), com marcador em disco
    sob videos/.locks. Usado pelo fluxo de vídeo, onde a chave não é só o produto."""
    def __init__(self, key: str):
        self._local = threading.Lock()
        self._marker_path = _LOCKS_DIR / (re.sub(r"[^A-Za-z0-9_-]", "_", key) + ".lock")
        self._marker: Path | None = None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def acquire(self, blocking=True, timeout=-1):
        acquired = self._local.acquire(False) if not blocking else self._local.acquire(True, timeout)
        if not acquired:
            return False
        marker = self._marker_path
        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            while True:
                try:
                    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode("ascii"))
                    os.close(fd)
                    self._marker = marker
                    return True
                except FileExistsError:
                    try:
                        pid = int(marker.read_text(encoding="ascii").strip())
                    except (OSError, ValueError):
                        pid = -1
                    if self._pid_alive(pid):
                        self._local.release()
                        return False
                    marker.unlink(missing_ok=True)
        except Exception:
            self._local.release()
            raise

    def release(self):
        if self._marker is not None:
            self._marker.unlink(missing_ok=True)
            self._marker = None
        self._local.release()


class _KeyJobManager:
    def __init__(self):
        self._locks: dict[str, _KeyLock] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._guard = threading.Lock()

    def lock(self, key: str) -> _KeyLock:
        with self._guard:
            return self._locks.setdefault(key, _KeyLock(key))

    def cancel(self, key: str) -> threading.Event:
        with self._guard:
            return self._cancels.setdefault(key, threading.Event())


VIDEO_JOBS = _KeyJobManager()
