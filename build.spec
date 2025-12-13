# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import sys
import platform
import fnmatch
from pathlib import Path
from collections import abc
from traceback import format_exc
from typing import Any, TypeAlias, TYPE_CHECKING

SELF_PATH = str(Path(".").resolve())
if SELF_PATH not in sys.path:
    sys.path.insert(0, SELF_PATH)

from constants import WORKING_DIR, SITE_PACKAGES_PATH, DEFAULT_LANG

if TYPE_CHECKING:
    from PyInstaller.building.splash import Splash
    from PyInstaller.building.build_main import Analysis
    from PyInstaller.building.datastruct import _TOCTuple
    from PyInstaller.building.api import PYZ, EXE, COLLECT


PYZTypeCOLLECT: TypeAlias = "abc.Iterable[_TOCTuple] | PYZ"
PYZTypeEXE: TypeAlias = "abc.Iterable[_TOCTuple] | PYZ | Splash"


# Simple configuration
upx: bool = False  # Use UPX compression (reduces file size, may increase AV detections)
console: bool = False  # True if you'd want to add a console window (useful for debugging)
one_dir: bool = False  # True for one-dir, False for one-file
optimize: int | None = None  # -1/None/0=none, 1=remove asserts, 2=also remove docstrings
app_name: str = "Twitch Drops Miner (by DevilXD)"


# (source_path, dest_path, required)
to_add: list[tuple[Path, str, bool]] = [
    # icon files
    (Path("icons/pickaxe.ico"), "./icons", True),
    (Path("icons/active.ico"), "./icons", True),
    (Path("icons/idle.ico"), "./icons", True),
    (Path("icons/error.ico"), "./icons", True),
    (Path("icons/maint.ico"), "./icons", True),
    # SeleniumWire HTTPS/SSL cert file and key
    (Path(SITE_PACKAGES_PATH, "seleniumwire/ca.crt"), "./seleniumwire", False),
    (Path(SITE_PACKAGES_PATH, "seleniumwire/ca.key"), "./seleniumwire", False),
]
for lang_filepath in WORKING_DIR.joinpath("lang").glob("*.json"):
    if lang_filepath.stem != DEFAULT_LANG:
        to_add.append((lang_filepath, "lang", True))

# Ensure the required to-be-added data exists
datas: list[tuple[Path, str]] = []
for source_path, dest_path, required in to_add:
    if source_path.exists():
        datas.append((source_path, dest_path))
    elif required:
        raise FileNotFoundError(str(source_path))

hooksconfig: dict[str, Any] = {}
binaries: list[tuple[Path, str]] = []
hiddenimports: list[str] = [
    "PIL._tkinter_finder",
    "setuptools._distutils.log",
    "setuptools._distutils.dir_util",
    "setuptools._distutils.file_util",
    "setuptools._distutils.archive_util",
]

if sys.platform == "linux":
    # Needed files for better system tray support on Linux via pystray (AppIndicator backend).
    arch: str = platform.machine()
    libraries_path: Path = Path(f"/usr/lib/{arch}-linux-gnu")
    if not libraries_path.exists():
        libraries_path = Path("/usr/lib64")
    datas.append(
        (libraries_path / "girepository-1.0/AyatanaAppIndicator3-0.1.typelib", "gi_typelibs")
    )
    binaries.append((libraries_path / "libayatana-appindicator3.so.1", "."))

    hiddenimports.extend([
        "gi.repository.Gtk",
        "gi.repository.GObject",
    ])
    hooksconfig = {
        "gi": {
            "icons": [],
            "themes": [],
            "languages": ["en_US"]
        }
    }

a = Analysis(
    ["main.py"],
    datas=datas,
    binaries=binaries,
    hooksconfig=hooksconfig,
    hiddenimports=hiddenimports,
)

# Exclude unneeded Linux libraries (supports globbing)
excluded_binaries = [
    "libicudata.so.*",
    "libicuuc.so.*",
    "librsvg-*.so.*"
]
a.binaries = [
    b for b in a.binaries
    if not any(fnmatch.fnmatch(b[0], pattern) for pattern in excluded_binaries)
]
if one_dir:
    exe_args: PYZTypeEXE = tuple()
    collect_args: PYZTypeCOLLECT = (a.datas, a.binaries)
else:
    exe_args = (a.datas, a.binaries)
    collect_args = tuple()

pyz = PYZ(a.pure)
try:
    exe = EXE(
        pyz,
        a.scripts,
        *exe_args,
        upx=upx,
        debug=False,
        name=app_name,
        console=console,
        optimize=optimize,
        exclude_binaries=one_dir,
        icon="icons/pickaxe.ico",
    )
except PermissionError as exc:
    exc_text: str = format_exc()
    if any(t in exc_text for t in ("os.remove", "os.unlink")):
        raise PermissionError("Ensure the executable isn't running when rebuilding.") from exc
    raise
if one_dir:
    coll = COLLECT(
        exe,
        *collect_args,
        upx=upx,
        name=app_name,
    )
