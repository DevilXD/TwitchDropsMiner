"""
Main entry point for Twitch Drops Miner.

This is the primary entry point that decides which UI backend to use based on
the UI_BACKEND environment variable:
- UI_BACKEND=tkinter (default) - Uses traditional tkinter desktop GUI
- UI_BACKEND=nicegui - Uses NiceGUI web interface

Usage:
    python entrypoint.py

Or with explicit backend:
    UI_BACKEND=nicegui python entrypoint.py
"""

from __future__ import annotations

import os
import sys
import subprocess


def main():
    """Run the appropriate entry point based on UI_BACKEND environment variable."""
    ui_backend = os.getenv("UI_BACKEND", "tkinter").lower()

    if ui_backend == "nicegui":
        print("Starting Twitch Drops Miner with WebUI backend...")
        script = "main_webui.py"
    elif ui_backend == "tkinter":
        print("Starting Twitch Drops Miner with tkinter backend...")
        script = "main.py"
    else:
        print(f"Error: Unknown UI_BACKEND '{ui_backend}'")
        print("Valid options: 'tkinter' (default) or 'nicegui'")
        sys.exit(1)

    # Run the selected entry point with the same Python interpreter
    try:
        result = subprocess.run([sys.executable, script] + sys.argv[1:])
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully without showing traceback
        sys.exit(0)


if __name__ == "__main__":
    main()
