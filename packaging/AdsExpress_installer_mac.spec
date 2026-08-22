# -*- mode: python ; coding: utf-8 -*-
"""Instalador premium do Ads Express para macOS — bundle .app com UI HTML (pywebview).

Espelha o AdsExpress_installer.spec (Windows), mas gera um "Ads Express Installer.app"
com backend Cocoa/WebKit. Roda DEPOIS de build_mac.sh (precisa do dist/Ads Express.app).

Build (num Mac, a partir da raiz):
    pyinstaller packaging/AdsExpress_installer_mac.spec --noconfirm --distpath dist

Sai dist/Ads Express Installer.app. Embute:
  - payload/Ads Express.app  -> o app buildado (o instalador copia pra /Applications)
  - installer_mac.html + app-1024.png (a UI)
  - _default_config/         -> config.toml semente
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

ROOT = os.path.abspath(os.getcwd())
TARGET_ARCH = os.environ.get("ADSEXPRESS_ARCH", "universal2")
APP_VERSION = os.environ.get("ADSEXPRESS_VERSION", "1.1.0")


def _p(*parts):
    return os.path.join(ROOT, *parts)


# --- payload (o app buildado) + assets da UI + config semente ---
datas = [
    (_p("dist", "Ads Express.app"), os.path.join("payload", "Ads Express.app")),
    (_p("packaging", "installer_ui", "installer_mac.html"), "."),
    (_p("packaging", "icons", "app-1024.png"), "."),
    (_p("packaging", "default_config"), "_default_config"),
]

# Produtos embutidos: o instalador copia pra pasta de dados do usuário (semente). São
# só as DEFINIÇÕES (o output/ gerado é gitignored e não existe no checkout limpo do CI).
for _seed_src, _seed_dst in (
    (_p("config", "products"), os.path.join("_seed", "config_products")),
    (_p("products"), os.path.join("_seed", "products")),
):
    if os.path.isdir(_seed_src):
        datas.append((_seed_src, _seed_dst))
binaries = []

# pywebview (UI) — colete tudo, igual ao app.
_wv_datas, _wv_binaries, _wv_hidden = collect_all("webview")
datas += _wv_datas
binaries += _wv_binaries

# certifi: CA bundle p/ o HTTPS da nodejs.org funcionar dentro do .app congelado.
try:
    _cf_datas, _cf_binaries, _cf_hidden = collect_all("certifi")
    datas += _cf_datas
    binaries += _cf_binaries
except Exception:  # noqa: BLE001
    _cf_hidden = ["certifi"]

hiddenimports = list(_wv_hidden) + list(_cf_hidden) + ["webview.platforms.cocoa", "certifi"]

# pyobjc: o backend Cocoa importa esses frameworks dinamicamente.
for _mod in ("objc", "Foundation", "AppKit", "WebKit", "Quartz", "Cocoa",
             "CoreFoundation", "PyObjCTools", "Security"):
    hiddenimports += collect_submodules(_mod)

a = Analysis(
    [_p("packaging", "installer_ui", "installer_mac.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Instalador é enxuto: não precisa de Flask/app/Qt/tkinter/toolkits Windows.
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6", "cefpython3",
              "clr", "clr_loader", "pythonnet", "flask", "jinja2", "werkzeug"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ads Express Installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # janela HTML, sem terminal
    disable_windowed_traceback=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
    icon=_p("packaging", "icons", "AdsExpress.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Ads Express Installer",
)

app = BUNDLE(
    coll,
    name="Ads Express Installer.app",
    icon=_p("packaging", "icons", "AdsExpress.icns"),
    bundle_identifier="com.adsexpress.installer",
    version=APP_VERSION,
    info_plist={
        "CFBundleName": "Ads Express Installer",
        "CFBundleDisplayName": "Ads Express Installer",
        "CFBundleExecutable": "Ads Express Installer",
        "CFBundleIdentifier": "com.adsexpress.installer",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundlePackageType": "APPL",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "CFBundleDevelopmentRegion": "pt_BR",
    },
)
