"""Point a frozen Windows build at its bundled Tcl/Tk resources."""

from __future__ import annotations

import os
import sys
from pathlib import Path


if hasattr(sys, "_MEIPASS"):
    root = Path(sys._MEIPASS)
    # Override inherited variables: the application must use the matching
    # Tcl/Tk version bundled alongside its own _tkinter extension.
    os.environ["TCL_LIBRARY"] = str(root / "_app_tcl")
    os.environ["TK_LIBRARY"] = str(root / "_app_tk")
