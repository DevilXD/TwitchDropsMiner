# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

SELF_PATH = str(Path(".").absolute())
if SELF_PATH not in sys.path:
    sys.path.insert(0, SELF_PATH)

from constants import WORKING_DIR, DEFAULT_LANG

if TYPE_CHECKING:
    from PyInstaller.building.api import PYZ, EXE
    from PyInstaller.building.build_main import Analysis


datas: list[tuple[str | Path, str]] = [
    ("pickaxe.ico", '.'),  # icon file
    # SeleniumWire HTTPS/SSL cert file and key
    ("./env/Lib/site-packages/seleniumwire/ca.crt", "./seleniumwire"),
    ("./env/Lib/site-packages/seleniumwire/ca.key", "./seleniumwire"),
]
for lang_filepath in WORKING_DIR.joinpath("lang").glob("*.json"):
    if lang_filepath.stem != DEFAULT_LANG:
        datas.append((lang_filepath, "lang"))

block_cipher = None
a = Analysis(
    ["main.py"],
    pathex=[],
    datas=datas,
    binaries=[],
    excludes=[],
    hookspath=[],
    hooksconfig={},
    noarchive=False,
    hiddenimports=[
        "setuptools._distutils.log",
        "setuptools._distutils.dir_util",
        "setuptools._distutils.file_util",
        "setuptools._distutils.archive_util",
    ],
    runtime_hooks=[],
    cipher=block_cipher,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    upx=True,
    debug=False,
    strip=False,
    console=False,
    upx_exclude=[],
    target_arch=None,
    icon="pickaxe.ico",
    runtime_tmpdir=None,
    codesign_identity=None,
    entitlements_file=None,
    bootloader_ignore_signals=False,
    disable_windowed_traceback=False,
    name="Twitch Drops Miner (by DevilXD)",
)
