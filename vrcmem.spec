# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VRCMem+."""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

from pathlib import Path

ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")
dnd_datas, dnd_binaries, dnd_hidden = collect_all("tkinterdnd2")
icon_file = Path("assets/icon.ico")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=ctk_binaries + dnd_binaries,
    datas=ctk_datas + dnd_datas + [("assets/icon.ico", "assets")],
    hiddenimports=[
        *ctk_hidden,
        *dnd_hidden,
        "PIL._tkinter_finder",
        "vrchatapi",
        "vrchatapi.api",
        "vrchatapi.api.authentication_api",
        "vrchatapi.api.files_api",
        "vrchatapi.api.prints_api",
        "vrchatapi.api.users_api",
        "vrchatapi.models",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VRCMemPlus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(icon_file) if icon_file.exists() else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VRCMemPlus",
)
