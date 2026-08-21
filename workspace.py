"""Primitives compartilhadas de segurança, persistência e jobs locais."""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import threading
import time
import uuid
from pathlib import Path

# --- Raiz de dados (fonte única de verdade) -----------------------------------
# Rodando como .exe congelado (PyInstaller), ROOT precisa ser a pasta que CONTÉM
# o executável — ali ficam config/ e gerados/, graváveis pelo usuário, ao lado do
# app — e NUNCA o bundle temporário sys._MEIPASS (só-leitura, apagado ao sair).
# Rodando do código-fonte (python desktop.py), ROOT é a pasta deste arquivo.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

# Bundle só-leitura (templates, static, prompts, backends, config default). Só
# existe quando congelado; no código-fonte é a própria ROOT.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT))


def _data_root() -> Path:
    """Onde ficam os dados GRAVÁVEIS do usuário (config/ e entregas/):
    - código-fonte: a própria pasta do projeto (comportamento idêntico ao de sempre);
    - Windows congelado: %LOCALAPPDATA%\\Ads Express — pasta ESTÁVEL do usuário, que
      NÃO some ao rebuildar/reinstalar o app e é compartilhada entre todas as cópias
      (antes era ao lado do .exe, o que apagava os dados a cada novo build);
    - macOS congelado: ~/Library/Application Support/Ads Express (mesma ideia; um .app
      em /Applications é SÓ-LEITURA e não pode gravar ao lado de si)."""
    # Override explícito (dev/diagnóstico): aponta os dados graváveis pra uma pasta
    # arbitrária — ex.: rodar o código-fonte lendo os dados do .exe congelado.
    override = os.environ.get("ADSEXPRESS_DATA_ROOT")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Ads Express"
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Ads Express"
    return Path(__file__).resolve().parent


# Raiz dos dados graváveis (config/ e gerados/). Separada de ROOT/BUNDLE_DIR porque
# no Mac o app fica em /Applications (só-leitura) e os dados vão pro Application Support.
DATA_ROOT = _data_root()


def _prepend_ao_path(dirs: list[str]) -> None:
    """Prepende diretórios ao PATH sem duplicar o que já existe. Preserva a ordem
    recebida (o primeiro da lista termina na frente do PATH)."""
    partes = (os.environ.get("PATH") or "").split(os.pathsep)
    novos = [d for d in dirs if d and d not in partes]
    if novos:
        os.environ["PATH"] = os.pathsep.join(novos + partes)


def _dirs_fixos_macos() -> list[str]:
    """Locais canônicos onde node/claude/codex/ffmpeg costumam viver no Mac.
    Vazio fora do macOS (o Windows usa só o cli_paths.env)."""
    if sys.platform != "darwin":
        return []
    return [
        "/opt/homebrew/bin", "/opt/homebrew/sbin",   # Apple Silicon (brew)
        "/usr/local/bin", "/usr/local/sbin",           # Intel (brew) / geral
        str(Path.home() / ".nvm" / "current" / "bin"),  # nvm (prometido no README_MAC)
        str(Path.home() / ".npm-global" / "bin"),      # npm prefix custom comum
        str(Path.home() / ".local" / "bin"),
    ]


def _dirs_cli_paths_env() -> list[str]:
    """Lê config/cli_paths.env (gravado pelo first-run de Mac/Windows) e devolve os
    DIRETÓRIOS dos binários registrados. O arquivo tem linhas `NODE_PATH=/abs/node`,
    `CLAUDE_PATH=...`, `CODEX_PATH=...`, `FFMPEG_PATH=...` (nome da ferramenta em
    MAIÚSCULAS + `_PATH`, valor = caminho absoluto do binário). Sem honrar isto, quem
    instalou Node via nvm ou prefixo npm custom fica com `shutil.which('claude')` ->
    None mesmo após o first-run. Robusto a arquivo ausente/malformado — nunca levanta."""
    dirs: list[str] = []
    try:
        arq = CONFIG_DIR / "cli_paths.env"
        if not arq.exists():
            return dirs
        for linha in arq.read_text(encoding="utf-8", errors="replace").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            _chave, _, valor = linha.partition("=")
            valor = valor.strip().strip('"').strip("'")
            if not valor:
                continue
            d = str(Path(valor).parent)
            if d and d not in dirs:
                dirs.append(d)
    except Exception:  # noqa: BLE001 — jamais quebrar o import de workspace por isto
        return dirs
    return dirs


def _augment_path() -> None:
    """Ajusta o PATH no IMPORT do módulo, ANTES de qualquer `shutil.which` em runtime.
    Apps de JANELA no macOS NÃO herdam o PATH do shell de login e o nvm/prefixo npm
    custom (Win e Mac) não fica nos diretórios canônicos — sem isto, todo subprocess
    (node/claude/codex/ffmpeg) falha porque o which volta None.
    Ordem final do PATH: cli_paths.env (mais específico/confiável) → diretórios fixos
    → PATH original. Prepende os fixos primeiro e o cli_paths por cima, para o
    cli_paths acabar na frente."""
    _prepend_ao_path(_dirs_fixos_macos())    # fixos primeiro…
    _prepend_ao_path(_dirs_cli_paths_env())  # …e cli_paths por cima (fica na frente)


# --- Layout de disco (fonte única de verdade) ---------------------------------
# config/  = TODA configuração + dados de entrada (config.toml, .env, produtos,
#            avatares, influenciadores) e o estado de trabalho do pipeline
#            (prompts.json, copies.md, formatos.json, status.json, cache .refs).
# gerados/ = SOMENTE as imagens de criativo geradas, em
#            gerados/<cliente|_sem-cliente>/<produto>/<DD-MM-YYYY>/ (o dia da geração).
CONFIG_DIR = DATA_ROOT / "config"
# Saídas geradas ficam agrupadas sob entregas/ (gerados/ + videos/) pra manter a
# raiz limpa: config/ = entradas, entregas/ = o que o app produz.
GERADOS_DIR = DATA_ROOT / "entregas" / "gerados"

# Ajusta o PATH assim que CONFIG_DIR existe (o cli_paths.env vive dentro dele) e
# ANTES de qualquer shutil.which em runtime.
_augment_path()


def _base(sub: str) -> Path:
    """Diretório de dados sob config/ (novo layout), com fallback à raiz (legado).
    Prefere config/<sub>; só cai na raiz quando SÓ o antigo existe (migração em curso)."""
    novo = CONFIG_DIR / sub
    antigo = DATA_ROOT / sub
    return antigo if (antigo.exists() and not novo.exists()) else novo


def _config_file(nome: str) -> Path:
    """config/<nome> se existir, senão ROOT/<nome> (compat pré-migração p/ config.toml/.env)."""
    novo = CONFIG_DIR / nome
    return novo if novo.exists() else DATA_ROOT / nome


PRODUCTS = _base("products")
AVATARES = _base("avatares")
# Influenciadores REAIS (fotos enviadas pelo usuário) dos criativos estáticos.
INFLUENCIADORES = _base("influenciadores")
# Vídeo UGC (fluxo separado do de imagem): escrita sob entregas/videos/.
VIDEOS = DATA_ROOT / "entregas" / "videos"
_LOCKS_DIR = VIDEOS / ".locks"
_PRODUCT_RE = re.compile(r"^[^\\/]+$")
# Nome de pasta de lote diário em gerados/: DD-MM-AAAA.
_DATA_LOTE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


def carregar_config() -> dict:
    import tomllib
    with open(_config_file("config.toml"), "rb") as f:
        return tomllib.load(f)


def carregar_env() -> None:
    """Carrega o .env no ambiente. Prefere config/.env; cai para ROOT/.env (compat)."""
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001 — dotenv é opcional
        return
    for p in (CONFIG_DIR / ".env", ROOT / ".env"):
        if p.exists():
            load_dotenv(p)
            return


def ensure_user_config() -> None:
    """Garante que exista config/config.toml gravável ao lado do app.

    No .exe congelado a primeira execução não traz config/ do usuário; copiamos o
    template embutido (BUNDLE_DIR/_default_config/config.toml) para ROOT/config/.
    Idempotente: NUNCA sobrescreve um config.toml já existente do usuário. No
    código-fonte é no-op (o config já está versionado em config/)."""
    destino = CONFIG_DIR / "config.toml"
    if destino.exists():
        return
    template = BUNDLE_DIR / "_default_config" / "config.toml"
    if not template.exists():
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(template, destino)
    except OSError:
        pass


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


# ---- gerados/ : imagens de criativo, agrupadas por cliente/produto/dia ----------

def _cliente_produto(produto: str) -> tuple[str, str]:
    """Quebra o id em (cliente, produto) para o layout de gerados/.
    Produto solto (sem '~') cai no bucket '_sem-cliente'."""
    if "~" in produto:
        cliente, _, prod = produto.partition("~")
        return cliente, prod
    return "_sem-cliente", produto


def gerados_dir_de_id(produto: str) -> Path:
    """gerados/<cliente|_sem-cliente>/<produto> a partir do id, SEM validar existência
    (usado ao mover/remover o produto, quando o id antigo já não resolve)."""
    cliente, prod = _cliente_produto(produto)
    base = GERADOS_DIR.resolve()
    d = (GERADOS_DIR / cliente / prod).resolve()
    if base not in d.parents:
        raise ValueError("Caminho de gerados inválido.")
    return d


def gerados_produto_dir(produto: str) -> Path:
    """gerados/<cliente|_sem-cliente>/<produto> (valida que o produto existe)."""
    product_dir(produto)
    return gerados_dir_de_id(produto)


def data_lote_hoje() -> str:
    from datetime import datetime
    return datetime.now().strftime("%d-%m-%Y")


def lote_dir(produto: str, data: str | None = None, *, create: bool = False) -> Path:
    """gerados/<cliente>/<produto>/<DD-MM-AAAA> — a pasta de um lote (dia)."""
    base = gerados_produto_dir(produto)
    data = data or data_lote_hoje()
    if not _DATA_LOTE_RE.fullmatch(data):
        raise ValueError("Data de lote inválida.")
    d = (base / data).resolve()
    if base.resolve() not in d.parents:
        raise ValueError("Caminho de lote inválido.")
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def lotes(produto: str) -> list[str]:
    """Datas de lote existentes (DD-MM-AAAA), da mais recente para a mais antiga."""
    from datetime import datetime
    base = gerados_produto_dir(produto)
    if not base.exists():
        return []
    nomes = [d.name for d in base.iterdir()
             if d.is_dir() and _DATA_LOTE_RE.fullmatch(d.name)]

    def _k(s: str):
        try:
            return datetime.strptime(s, "%d-%m-%Y")
        except ValueError:
            return datetime.min

    return sorted(nomes, key=_k, reverse=True)


def criativos_dir(produto: str, *, para_gerar: bool = False, create: bool = False) -> Path:
    """Pasta ATIVA de criativos (o lote em foco), em gerados/.

    para_gerar=True: SEMPRE o lote de HOJE (uma nova geração abre a pasta do dia).
    Senão: o lote existente mais recente e, se ainda não houver nenhum, o de hoje.
    É o substituto direto do antigo `product/output/criativos`."""
    if not para_gerar:
        existentes = lotes(produto)
        if existentes:
            return lote_dir(produto, existentes[0], create=create)
    return lote_dir(produto, create=create)


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
