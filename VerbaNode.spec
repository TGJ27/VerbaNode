# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve()


def safe_collect(package: str):
    try:
        return collect_all(package)
    except Exception:
        return ([], [], [])


datas = [
    (str(ROOT / "app" / "static"), "app/static"),
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "plugins"), "plugins"),
]
binaries = []
hiddenimports = [
    "app.main",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

# VerbaNode loads several providers dynamically. Collect their Python modules,
# package data, and native libraries into the onedir bundle. The helper keeps
# the spec readable while relying on PyInstaller's package-specific hooks.
for package in (
    "funasr",
    "modelscope",
    "whisper",
    "edge_tts",
    "sherpa_onnx",
    "silero_vad",
    "sounddevice",
    "soundfile",
    "onnxruntime",
    "ollama",
    "cryptography",
    "customtkinter",
):
    package_datas, package_binaries, package_hidden = safe_collect(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

hiddenimports += collect_submodules("app")

# Avoid PyInstaller trying to collect GUI frameworks pulled indirectly by
# optional ML dependencies. VerbaNode's native launcher uses CustomTkinter
# (which is still Tk-based) and is collected explicitly above.
excludes = ["PyQt5", "PyQt6", "PySide2", "PySide6"]

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VerbaNode",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "assets" / "VerbaNode.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VerbaNode",
)
