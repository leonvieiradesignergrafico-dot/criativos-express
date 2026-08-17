# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para o assistente 'Setup Ads Express' (console, one-folder).

Build:
    pyinstaller packaging/Setup.spec --noconfirm

Gera dist/Setup Ads Express/Setup Ads Express.exe — COM console (o usuário precisa
ver o progresso e interagir com os logins das CLIs). Copie esse .exe para a MESMA
pasta do "Ads Express.exe" (o instalador faz isso).
"""
import os

ROOT = os.path.abspath(os.getcwd())


a = Analysis(
    [os.path.join(ROOT, "packaging", "first_run_setup.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PySide6", "webview", "flask", "PIL", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Setup Ads Express",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,                # console visível: progresso + logins interativos
    icon=os.path.join(ROOT, "packaging", "icons", "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Setup Ads Express",
)
