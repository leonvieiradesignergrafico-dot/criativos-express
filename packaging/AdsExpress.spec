# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para o Ads Express (Criativos Express).

Build:
    cd "<raiz do projeto>"
    pyinstaller packaging/AdsExpress.spec --noconfirm

Gera dist/Ads Express/ (one-folder). O executável é "Ads Express.exe", sem
janela de console (windowed). config/ e gerados/ são criados ao lado do .exe na
primeira execução (ver workspace.py: ROOT = pasta do executável quando congelado).
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

# A raiz do projeto é o diretório de trabalho na hora do build (onde roda o pyinstaller).
ROOT = os.path.abspath(os.getcwd())


def _p(*parts):
    return os.path.join(ROOT, *parts)


# --- Assets só-leitura embutidos (templates/estáticos/prompts + config default) ---
datas = [
    (_p("app", "templates"), os.path.join("app", "templates")),
    (_p("app", "static"), os.path.join("app", "static")),
    (_p("app", "prompts"), os.path.join("app", "prompts")),
    (_p("packaging", "default_config"), "_default_config"),
]

binaries = []

# webview traz a DLL do WebView2 loader + backends de plataforma: colete tudo.
_wv_datas, _wv_binaries, _wv_hidden = collect_all("webview")
datas += _wv_datas
binaries += _wv_binaries

hiddenimports = list(_wv_hidden)
# Backends de janela do pywebview no Windows (escolhidos em runtime).
hiddenimports += [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "webview.platforms.cef",
    "webview.platforms.mshtml",
    "webview.platforms.win32",
]
# pythonnet / clr — o backend EdgeChromium (winforms) depende deles.
hiddenimports += ["clr", "clr_loader", "pythonnet", "proxy_tools", "bottle"]
# Nossos pacotes com imports dinâmicos (escolhidos por config em runtime).
hiddenimports += collect_submodules("backends")
hiddenimports += collect_submodules("app.pipeline")
hiddenimports += ["app.server", "app.ugc_web", "gerar", "workspace"]
# Stdlib/terceiros que a análise às vezes perde.
hiddenimports += ["tomllib", "dotenv", "PIL", "PIL.Image"]


a = Analysis(
    [_p("desktop.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6", "cefpython3"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ads Express",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # sem janela de CMD
    disable_windowed_traceback=False,
    icon=_p("packaging", "icons", "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Ads Express",
)
