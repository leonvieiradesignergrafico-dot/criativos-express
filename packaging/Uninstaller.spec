# -*- mode: python ; coding: utf-8 -*-
"""Desinstalador do Ads Express — exe único pequeno (uninstall.exe).

Build (a partir da raiz):  pyinstaller packaging/Uninstaller.spec --noconfirm
Sai em dist/uninstall.exe. É embutido no instalador e copiado pra pasta do app.
"""
import os

ROOT = os.path.abspath(os.getcwd())


def _p(*parts):
    return os.path.join(ROOT, *parts)


a = Analysis(
    [_p("packaging", "installer_ui", "uninstaller.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6", "numpy", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="uninstall",
    debug=False,
    strip=False,
    upx=False,
    console=False,               # usa MessageBox nativo, sem console
    runtime_tmpdir=None,
    icon=_p("packaging", "icons", "app.ico"),
)
