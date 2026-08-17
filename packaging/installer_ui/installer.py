"""Instalador do Ads Express — janela HTML premium (pywebview), estilo do app.

Empacotado com PyInstaller (AdsExpress_installer.spec) embutindo:
  - payload/           -> os arquivos do app (dist/Ads Express/*)
  - uninstall.exe      -> o desinstalador (registrado em Adicionar/Remover Programas)
  - installer.html     -> a UI
  - app-1024.png       -> ícone (vira data URI na UI)

Fluxo: copia o payload pra %LOCALAPPDATA%\\Programs\\Ads Express, cria atalhos
(Menu Iniciar + Área de trabalho) e registra a desinstalação. Tudo per-user (sem admin).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import winreg
from pathlib import Path

# O backend winforms do pywebview loga um erro de acessibilidade em loop (~2/s) na
# janela frameless CONGELADA — inofensivo e invisível no duplo-clique (stderr é
# descartado), mas silenciamos pra não vazar ruído se algo capturar o stderr.
logging.getLogger("pywebview").setLevel(logging.CRITICAL)

import webview

APP_NAME = "Ads Express"
APP_EXE = "Ads Express.exe"
VERSION = "1.1.0"
PUBLISHER = "Ads Express"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AdsExpress"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _res(nome: str) -> Path:
    """Recurso embutido (no .exe congelado vive em _MEIPASS; no fonte, ao lado)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / nome


def _dest() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "Programs" / APP_NAME


def _start_menu_lnk() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def _desktop_lnk() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop" / f"{APP_NAME}.lnk"


def _criar_atalho(lnk: Path, target: Path, workdir: Path) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    ps = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
        f"$s.TargetPath='{target}';$s.IconLocation='{target}';"
        f"$s.WorkingDirectory='{workdir}';$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=_NO_WINDOW, check=False)


def _registrar_desinstalacao(dest: Path, tamanho_kb: int) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        def s(nome, val):
            winreg.SetValueEx(k, nome, 0, winreg.REG_SZ, str(val))
        s("DisplayName", APP_NAME)
        s("DisplayVersion", VERSION)
        s("Publisher", PUBLISHER)
        s("DisplayIcon", dest / APP_EXE)
        s("InstallLocation", dest)
        s("UninstallString", f'"{dest / "uninstall.exe"}"')
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, tamanho_kb)


class API:
    def __init__(self):
        self.window = None

    # -- chamado pela UI --
    def instalar(self):
        threading.Thread(target=self._instalar, daemon=True).start()

    def abrir_app(self):
        exe = _dest() / APP_EXE
        try:
            subprocess.Popen([str(exe)], cwd=str(_dest()))
        except OSError:
            pass
        self.fechar()

    def fechar(self):
        if self.window:
            self.window.destroy()

    # -- interno --
    def _prog(self, pct, msg):
        if self.window:
            self.window.evaluate_js(
                f"window.setProgress({int(pct)}, {json.dumps(msg, ensure_ascii=False)})")

    def _instalar(self):
        try:
            payload = _res("payload")
            dest = _dest()
            self._prog(2, "Preparando…")
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True, exist_ok=True)

            arquivos = [p for p in payload.rglob("*") if p.is_file()]
            total = max(len(arquivos), 1)
            for i, src in enumerate(arquivos, 1):
                rel = src.relative_to(payload)
                alvo = dest / rel
                alvo.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, alvo)
                if i % 12 == 0 or i == total:
                    self._prog(2 + i / total * 88, "Copiando arquivos…")

            self._prog(92, "Criando atalhos…")
            unin = _res("uninstall.exe")
            if unin.exists():
                shutil.copy2(unin, dest / "uninstall.exe")
            _criar_atalho(_start_menu_lnk(), dest / APP_EXE, dest)
            _criar_atalho(_desktop_lnk(), dest / APP_EXE, dest)

            self._prog(97, "Registrando…")
            kb = sum(f.stat().st_size for f in arquivos) // 1024
            _registrar_desinstalacao(dest, kb)

            self._prog(100, "Concluído")
            if self.window:
                self.window.evaluate_js("window.setDone()")
        except Exception as e:  # noqa: BLE001
            if self.window:
                self.window.evaluate_js(f"window.setErro({json.dumps(str(e))})")


def _html() -> str:
    html = _res("installer.html").read_text(encoding="utf-8")
    ico = base64.b64encode(_res("app-1024.png").read_bytes()).decode()
    return html.replace("{{ICON}}", f"data:image/png;base64,{ico}").replace("{{VERSION}}", VERSION)


def main():
    # App windowed congelado: stderr não existe pro usuário; garante que nenhum ruído
    # do backend vaze mesmo se o processo for iniciado com um stderr conectado.
    if getattr(sys, "frozen", False):
        try:
            sys.stderr = open(os.devnull, "w")  # noqa: SIM115
        except OSError:
            pass
    api = API()
    win = webview.create_window(
        APP_NAME, html=_html(), js_api=api,
        width=520, height=600, resizable=False, frameless=True, easy_drag=False,
        background_color="#0d0d0f",  # easy_drag OFF: evita o spam de acessibilidade do winforms
    )
    api.window = win
    webview.start()


if __name__ == "__main__":
    main()
