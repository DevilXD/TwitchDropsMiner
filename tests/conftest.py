"""
Conftest for TwitchDropsMiner tests.

Fixes two import-time issues that break when running under pytest:

1. Module name collision: the project's websocket.py shadows the ``websocket``
   pip package that python-engineio (a NiceGUI dependency) tries to import at
   module level.  When ``engineio.client`` does ``import websocket``, it finds
   the project file, which cascades into translate.py → constants.py and tries
   to write files to the wrong directory.  We pre-seed sys.modules with a
   lightweight stub so the project file is never triggered through that path.

2. Path resolution: constants.py derives WORKING_DIR from sys.argv[0], which
   may not point to the project directory at test time.  We patch it so the
   project root is used instead.
"""

from __future__ import annotations

import types
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Fix 1: websocket module collision ----------------------------------------
_ws_stub = types.ModuleType("websocket")
_ws_stub.__path__ = []
_ws_stub.__file__ = "<websocket stub for testing>"
sys.modules.setdefault("websocket", _ws_stub)

# --- Fix 2: Path resolution ---------------------------------------------------
# constants.py uses sys.argv[0] to compute SELF_PATH / WORKING_DIR / LANG_PATH.
# Under pytest, sys.argv[0] may be the python interpreter itself (not the
# project entry point), which makes translate.py try writing language files
# to the wrong directory.  Unconditionally override to the project root.
sys.argv[0] = str(PROJECT_ROOT / "main_webui.py")
