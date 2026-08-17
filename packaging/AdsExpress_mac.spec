# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para o Ads Express no macOS (bundle .app).

Build (num Mac — ver packaging/mac/build_mac.sh, que automatiza tudo):
    cd "<raiz do projeto>"
    pyinstaller packaging/AdsExpress_mac.spec --noconfirm

Gera:
    dist/Ads Express.app          <- o bundle que o usuário arrasta pra /Applications

Diferenças em relação ao AdsExpress.spec (Windows):
  - windowed/console=False, ícone .icns, e um objeto BUNDLE() com Info.plist.
  - backend de janela do pywebview é o Cocoa/WebKit (não o EdgeChromium do Windows);
    os hidden imports refletem isso (webview.platforms.cocoa + pyobjc).
  - Info.plist inclui a exceção de App Transport Security p/ liberar http://127.0.0.1
    (senão o WebKit embutido bloqueia o Flask local e a janela fica em branco).
  - target_arch='universal2' (roda em Apple Silicon E Intel). Ver nota no fim.

DADOS GRAVÁVEIS (importante): um .app dentro de /Applications é SÓ-LEITURA, então
config/ e gerados/ NÃO podem morar ao lado do executável (como no Windows). No Mac
eles vão para ~/Library/Application Support/Ads Express/. Isso é responsabilidade do
workspace.py (a resolver pelo agente principal) e do first_run_mac.command (que
semeia a pasta). Este spec só empacota os assets só-leitura.
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

# A raiz do projeto é o diretório de trabalho na hora do build (onde roda o pyinstaller).
ROOT = os.path.abspath(os.getcwd())

# Arquitetura alvo. universal2 exige que o Python E todas as deps binárias (pyobjc,
# pillow, etc.) sejam universais. Se o seu ambiente for single-arch, exporte antes:
#     export ADSEXPRESS_ARCH=arm64      (ou x86_64)
# e o build sai só pra essa arquitetura (sem erro de "não é universal2").
TARGET_ARCH = os.environ.get("ADSEXPRESS_ARCH", "universal2")

# Versão exibida no Finder / "Obter Informações". Bump manual a cada release.
APP_VERSION = os.environ.get("ADSEXPRESS_VERSION", "1.0.0")


def _p(*parts):
    return os.path.join(ROOT, *parts)


# --- Assets só-leitura embutidos (templates/estáticos/prompts + backends + config default) ---
datas = [
    (_p("app", "templates"), os.path.join("app", "templates")),
    (_p("app", "static"), os.path.join("app", "static")),
    (_p("app", "prompts"), os.path.join("app", "prompts")),
    (_p("packaging", "default_config"), "_default_config"),
]

binaries = []

# pywebview traz backends de plataforma escolhidos em runtime: colete tudo.
_wv_datas, _wv_binaries, _wv_hidden = collect_all("webview")
datas += _wv_datas
binaries += _wv_binaries

hiddenimports = list(_wv_hidden)

# Backend de janela do pywebview no macOS = Cocoa (WebKit). NÃO os do Windows.
hiddenimports += [
    "webview.platforms.cocoa",
]

# pyobjc: o backend Cocoa importa esses frameworks dinamicamente. Sem eles a
# janela nem abre. objc/Foundation/AppKit/WebKit/Quartz cobrem o que o pywebview usa.
for _mod in ("objc", "Foundation", "AppKit", "WebKit", "Quartz", "Cocoa",
             "CoreFoundation", "PyObjCTools", "Security"):
    hiddenimports += collect_submodules(_mod)

# Nossos pacotes com imports dinâmicos (escolhidos por config em runtime).
hiddenimports += collect_submodules("backends")
hiddenimports += collect_submodules("app.pipeline")
hiddenimports += ["app.server", "app.ugc_web", "gerar", "workspace"]

# Flask/Jinja e stdlib/terceiros que a análise às vezes perde.
hiddenimports += [
    "flask", "jinja2", "werkzeug", "click", "itsdangerous", "markupsafe",
    "tomllib", "dotenv", "PIL", "PIL.Image",
]


a = Analysis(
    [_p("desktop.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # No Mac não usamos os toolkits Windows nem Qt; tkinter puxa Tcl/Tk à toa.
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6", "cefpython3",
              "clr", "clr_loader", "pythonnet"],
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
    console=False,                 # windowed: sem terminal atrás da janela
    disable_windowed_traceback=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,        # assinatura é feita depois, por codesign_notarize.sh
    entitlements_file=None,
    icon=_p("packaging", "icons", "AdsExpress.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Ads Express",
)

# --- Bundle .app (com Info.plist) ---------------------------------------------
app = BUNDLE(
    coll,
    name="Ads Express.app",
    icon=_p("packaging", "icons", "AdsExpress.icns"),
    bundle_identifier="com.adsexpress.app",
    version=APP_VERSION,
    info_plist={
        "CFBundleName": "Ads Express",
        "CFBundleDisplayName": "Ads Express",
        "CFBundleExecutable": "Ads Express",
        "CFBundleIdentifier": "com.adsexpress.app",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundlePackageType": "APPL",
        "NSHighResolutionCapable": True,
        # macOS mínimo. Big Sur (11.0) é o piso do universal2 / Apple Silicon.
        "LSMinimumSystemVersion": "11.0",
        # App só-leitura em background curto: não é agente. Sem ícone no Dock? Não —
        # queremos ícone e janela normais, então LSUIElement fica falso (default).
        "LSApplicationCategoryType": "public.app-category.productivity",
        # --- App Transport Security -------------------------------------------
        # O Flask local serve HTTP puro em http://127.0.0.1:5000. Sem esta exceção
        # o WebKit dentro do .app bloqueia a conexão (janela em branco). NSAllowsLocalNetworking
        # libera loopback/hostnames locais SEM afrouxar o ATS para a internet.
        "NSAppTransportSecurity": {
            "NSAllowsLocalNetworking": True,
        },
        # Idioma padrão da UI (a app é PT-BR).
        "CFBundleDevelopmentRegion": "pt_BR",
    },
)
