"""Simplified UI factory that uses environment variable to select backend.

Set UI_BACKEND environment variable to choose the interface:
- UI_BACKEND=tkinter (default) - Uses tkinter desktop GUI
- UI_BACKEND=nicegui - Uses NiceGUI web interface
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from twitch import Twitch
    from gui import GUIManager
    from webui import WebUIManager


def create_gui_manager(twitch: "Twitch") -> Union["GUIManager", "WebUIManager"]:
    """
    Create the appropriate GUI manager based on UI_BACKEND environment variable.

    Defaults to tkinter if UI_BACKEND is not set or is an unknown value.
    """
    ui_backend = os.getenv("UI_BACKEND", "tkinter").lower()

    if ui_backend == "nicegui":
        from webui import WebUIManager

        return WebUIManager(twitch)
    else:
        from gui import GUIManager

        return GUIManager(twitch)
