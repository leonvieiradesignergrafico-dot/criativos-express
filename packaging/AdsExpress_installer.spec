# -*- mode: python ; coding: utf-8 -*-
"""Instalador premium do Ads Express — exe ÚNICO com UI HTML (pywebview).

Build (a partir da raiz, DEPOIS de gerar dist/Ads Express e dist/uninstall.exe):
    pyinstaller packaging/AdsExpress_installer.spec --noconfirm --distpath .

Sai AdsExpress-Setup-1.1.0.exe na RAIZ. Embute:
  - payload/        -> dist/Ads Express/*  (os arquivos do app)
  - uninstall.exe   -> dist/uninstall.exe  (desinstalador)
  - installer.html + app-1024.png (a UI)
"""
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.getcwd())


def _p(*parts):
    return os.path.join(ROOT, *parts)


datas = [
    (_p("dist", "Ads Express"), "payload"),
    (_p("dist", "uninstall.exe"), "."),
    (_p("packaging", "installer_ui", "installer.html"), "."),
    (_p("packaging", "icons", "app-1024.png"), "."),
]
binaries = []

# pywebview (UI da janela) — mesma coleta do app.
_wv_datas, _wv_binaries, _wv_hidden = collect_all("webview")
datas += _wv_datas
binaries += _wv_binaries

hiddenimports = list(_wv_hidden) + [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "webview.platforms.mshtml",
    "webview.platforms.win32",
    "clr", "clr_loader", "pythonnet", "proxy_tools", "bottle",
]

a = Analysis(
    [_p("packaging", "installer_ui", "installer.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6", "cefpython3", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="AdsExpress-Setup-1.1.0",
    debug=False,
    strip=False,
    upx=False,
    console=False,               # janela HTML, sem CMD
    runtime_tmpdir=None,
    icon=_p("packaging", "icons", "app.ico"),
)
