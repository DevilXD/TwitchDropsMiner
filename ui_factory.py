from __future__ import annotations

import os
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from twitch import Twitch
    from gui import GUIManager
    from webui import WebUIManager


def create_gui_manager(twitch: Twitch) -> Union['GUIManager', 'WebUIManager']:
    """
    Factory function to create either a tkinter GUI or NiceGUI web interface
    based on the UI_BACKEND environment variable.

    Environment Variables:
        UI_BACKEND: Set to "nicegui" to use web UI, "tkinter" for desktop GUI (default: tkinter)
        WEBUI_HOST: Host for web UI (default: 0.0.0.0)
        WEBUI_PORT: Port for web UI (default: 8080)

    Returns:
        GUIManager or WebUIManager instance with compatible interface
    """
    ui_backend = os.getenv('UI_BACKEND', 'tkinter').lower()

    if ui_backend == 'nicegui':
        try:
            from webui import WebUIManager
            print("Using NiceGUI web interface")

            # Get host and port from environment
            host = os.getenv('WEBUI_HOST', '0.0.0.0')
            port = int(os.getenv('WEBUI_PORT', '8080'))

            print(f"Web UI will be available at http://{host}:{port}")
            return WebUIManager(twitch, host=host, port=port)

        except ImportError as e:
            print(f"Warning: Failed to import NiceGUI web UI: {e}")
            print("Falling back to tkinter GUI")
            print("To use web UI, install NiceGUI: pip install nicegui")
    elif ui_backend == 'tkinter':
        pass  # Use default tkinter GUI
    else:
        print(f"Warning: Unknown UI backend '{ui_backend}'. Valid options: 'tkinter', 'nicegui'")
        print("Falling back to tkinter GUI")

    # Default to tkinter GUI
    from gui import GUIManager
    print("Using tkinter GUI")
    return GUIManager(twitch)


def is_webui_enabled() -> bool:
    """Check if web UI is enabled via environment variable"""
    return os.getenv('UI_BACKEND', 'tkinter').lower() == 'nicegui'


def get_webui_config() -> tuple[str, int]:
    """Get web UI host and port configuration"""
    host = os.getenv('WEBUI_HOST', '0.0.0.0')
    port = int(os.getenv('WEBUI_PORT', '8080'))
    return host, port