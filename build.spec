# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

SELF_PATH = str(Path(".").absolute())
if SELF_PATH not in sys.path:
    sys.path.insert(0, SELF_PATH)

from constants import WORKING_DIR, SITE_PACKAGES_PATH, DEFAULT_LANG

if TYPE_CHECKING:
    from PyInstaller.building.api import PYZ, EXE
    from PyInstaller.building.build_main import Analysis

# (source_path, dest_path, required)
to_add: list[tuple[Path, str, bool]] = [
    (Path("pickaxe.ico"), '.', True),  # icon file
    # SeleniumWire HTTPS/SSL cert file and key
    (Path(SITE_PACKAGES_PATH, "seleniumwire/ca.crt"), "./seleniumwire", False),
    (Path(SITE_PACKAGES_PATH, "seleniumwire/ca.key"), "./seleniumwire", False),
]
for lang_filepath in WORKING_DIR.joinpath("lang").glob("*.json"):
    if lang_filepath.stem != DEFAULT_LANG:
        to_add.append((lang_filepath, "lang", True))

# ensure the required to-be-added data exists
datas: list[tuple[Path, str]] = []
for source_path, dest_path, required in to_add:
    if source_path.exists():
        datas.append((source_path, dest_path))
    elif required:
        raise FileNotFoundError(str(source_path))


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
        "PIL._tkinter_finder",
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
