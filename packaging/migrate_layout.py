"""Migra o layout em disco para o novo formato (config/ + gerados/).

Antes:
    <raiz>/config.toml, <raiz>/.env
    <raiz>/products/<...>/{config.md, referencia/, contexto/, output/}
    <raiz>/products/<...>/output/criativos/*.png        (imagens geradas)
    <raiz>/avatares/, <raiz>/influenciadores/

Depois:
    <raiz>/config/config.toml, <raiz>/config/.env
    <raiz>/config/products/<...>/{config.md, referencia/, contexto/, output/}
    <raiz>/config/products/<...>/output/{prompts.json, copies.md, formatos.json,
                                         status.json, .refs, ...}   (estado de trabalho)
    <raiz>/config/avatares/, <raiz>/config/influenciadores/
    <raiz>/gerados/<cliente|_sem-cliente>/<produto>/<DD-MM-AAAA>/*.png  (imagens)

Regras:
  - MOVE, nunca apaga dados. As imagens são agrupadas em pastas de dia pela data de
    modificação (os.path.getmtime) de cada arquivo.
  - Idempotente: rodar de novo não desfaz nem duplica nada (pula o que já migrou).
  - videos/ fica onde está (fora do escopo).

Uso:  python packaging/migrate_layout.py
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
GERADOS_DIR = ROOT / "gerados"
PRODUCTS_DST = CONFIG_DIR / "products"

# Lixo transitório dentro de criativos/: pode ser removido (não é dado do usuário).
_TRANSIENTES_DIR = {".codex_scratch"}
_TRANSIENTES_PREFIX = (".refino-status-",)
_TRANSIENTES_NOME = {".generation.lock"}
_SUBPASTAS_IMG = ("finais", "descartados", "historico")

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


class Manifest:
    def __init__(self):
        self.linhas: list[str] = []
        self.buckets: dict[str, int] = {}
        self.produtos = 0
        self.imgs = 0
        self.config_files = 0
        self.subpastas = 0
        self.transientes = 0

    def log(self, msg: str) -> None:
        self.linhas.append(msg)
        print(msg)


def _move(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino))


def _mover_arquivo_unico(origem: Path, destino: Path) -> Path:
    """Move um arquivo evitando colisão de nome (sufixa com a hora)."""
    if destino.exists():
        destino = destino.with_name(
            f"{destino.stem}_{datetime.now().strftime('%H%M%S%f')}{destino.suffix}")
    _move(origem, destino)
    return destino


def _data_mtime(p: Path) -> str:
    return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%d-%m-%Y")


def _is_product(d: Path) -> bool:
    """Folha = produto (tem config.md/contexto/output/referencia). Senão, é cliente."""
    return any((d / n).exists() for n in ("config.md", "contexto", "output", "referencia"))


def _mover_dir_config(nome: str, m: Manifest) -> None:
    """Move <raiz>/<nome> -> config/<nome> (produtos, avatares, influenciadores)."""
    origem = ROOT / nome
    destino = CONFIG_DIR / nome
    if destino.exists():
        m.log(f"  [pula] config/{nome} já existe.")
        return
    if not origem.exists():
        m.log(f"  [pula] {nome}/ não existe na raiz.")
        return
    _move(origem, destino)
    m.log(f"  [move] {nome}/ -> config/{nome}/")


def _mover_config_file(nome: str, m: Manifest) -> None:
    origem = ROOT / nome
    destino = CONFIG_DIR / nome
    if destino.exists():
        m.log(f"  [pula] config/{nome} já existe.")
        return
    if not origem.exists():
        m.log(f"  [pula] {nome} não existe na raiz.")
        return
    _move(origem, destino)
    m.config_files += 1
    m.log(f"  [move] {nome} -> config/{nome}")


def _iter_produtos():
    """Gera (product_path, cliente, produto) a partir de config/products/."""
    if not PRODUCTS_DST.exists():
        return
    for d in sorted(PRODUCTS_DST.iterdir()):
        if not d.is_dir():
            continue
        if _is_product(d):
            yield d, "_sem-cliente", d.name
        else:
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and _is_product(sub):
                    yield sub, d.name, sub.name


def _migrar_criativos_produto(pdir: Path, cliente: str, produto: str, m: Manifest) -> None:
    criativos = pdir / "output" / "criativos"
    if not criativos.exists():
        return
    gerados_base = GERADOS_DIR / cliente / produto
    label = f"{cliente}/{produto}"

    # 1) status.json (estado de trabalho) volta para output/ (fora de gerados).
    st = criativos / "status.json"
    if st.exists():
        dst = pdir / "output" / "status.json"
        if not dst.exists():
            _move(st, dst)
            m.log(f"  [{label}] status.json -> output/status.json")
        else:
            st.unlink()  # já existe um status novo; o antigo é redundante

    # 2) PNGs (e demais imagens) diretos em criativos/ -> bucket por data de mtime.
    datas_usadas: list[str] = []
    for p in sorted(criativos.iterdir()):
        if not (p.is_file() and p.suffix.lower() in IMG_EXTS):
            continue
        data = _data_mtime(p)
        _mover_arquivo_unico(p, gerados_base / data / p.name)
        datas_usadas.append(data)
        m.imgs += 1
        m.buckets[data] = m.buckets.get(data, 0) + 1

    # bucket-alvo para as subpastas de imagem (finais/descartados/historico):
    # a data mais recente já usada, ou hoje se o produto não tinha PNGs soltos.
    def _key(s: str):
        try:
            return datetime.strptime(s, "%d-%m-%Y")
        except ValueError:
            return datetime.min

    bucket_alvo = max(datas_usadas, key=_key) if datas_usadas else datetime.now().strftime("%d-%m-%Y")

    # 3) subpastas de imagem -> dentro do bucket-alvo (merge, preservando estrutura).
    for sub in _SUBPASTAS_IMG:
        sp = criativos / sub
        if not sp.exists():
            continue
        destino = gerados_base / bucket_alvo / sub
        if not destino.exists():
            _move(sp, destino)
        else:
            for item in sp.iterdir():
                if item.is_file():
                    _mover_arquivo_unico(item, destino / item.name)
                else:
                    _move(item, destino / item.name)
            shutil.rmtree(sp, ignore_errors=True)
        m.subpastas += 1
        m.log(f"  [{label}] criativos/{sub}/ -> gerados/{cliente}/{produto}/{bucket_alvo}/{sub}/")

    # 4) transitórios: remove (lixo de sandbox/lock, não é dado do usuário).
    for p in list(criativos.iterdir()):
        nome = p.name
        if (nome in _TRANSIENTES_DIR or nome in _TRANSIENTES_NOME
                or any(nome.startswith(pref) for pref in _TRANSIENTES_PREFIX)):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            m.transientes += 1

    # 5) o que sobrou (ex.: caches .hashes_*.json) volta para output/ (estado de trabalho).
    for p in list(criativos.iterdir()):
        dst = pdir / "output" / p.name
        if p.is_file() and not dst.exists():
            _move(p, dst)
            m.log(f"  [{label}] criativos/{p.name} -> output/{p.name}")

    # 6) remove criativos/ se ficou vazio.
    try:
        if not any(criativos.iterdir()):
            criativos.rmdir()
    except OSError:
        pass

    m.produtos += 1


def main() -> int:
    m = Manifest()
    print("=" * 72)
    print("MIGRAÇÃO DE LAYOUT — Criativos Express")
    print(f"Raiz: {ROOT}")
    print("=" * 72)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/3] Config (config.toml, .env) -> config/")
    _mover_config_file("config.toml", m)
    _mover_config_file(".env", m)

    print("\n[2/3] Dados de entrada -> config/")
    _mover_dir_config("products", m)
    _mover_dir_config("avatares", m)
    _mover_dir_config("influenciadores", m)

    print("\n[3/3] Imagens geradas -> gerados/<cliente>/<produto>/<DD-MM-AAAA>/")
    if not PRODUCTS_DST.exists():
        print("  [aviso] config/products/ não existe — nada de imagens a migrar.")
    for pdir, cliente, produto in _iter_produtos():
        _migrar_criativos_produto(pdir, cliente, produto, m)

    print("\n" + "=" * 72)
    print("RESUMO")
    print("=" * 72)
    print(f"  Arquivos de config movidos : {m.config_files} (config.toml/.env)")
    print(f"  Produtos com criativos     : {m.produtos}")
    print(f"  Imagens movidas p/ gerados : {m.imgs}")
    print(f"  Subpastas de imagem movidas: {m.subpastas} (finais/descartados/historico)")
    print(f"  Transitórios removidos     : {m.transientes} (.codex_scratch/.lock/...)")
    if m.buckets:
        print("  Imagens por dia (bucket):")
        for data in sorted(m.buckets, key=lambda s: datetime.strptime(s, "%d-%m-%Y")):
            print(f"    {data}: {m.buckets[data]}")
    print("\n  videos/ : mantido na raiz (fora do escopo).")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
