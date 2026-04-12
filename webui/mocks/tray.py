from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class MockTray:
    """Mock system tray - no-op for web UI"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def change_icon(self, icon_name: str):
        pass

    def update_title(self, drop):
        pass

    def restore(self):
        pass

    def stop(self):
        pass

    def notify(self, message: str, title: str | None = None, duration: float = 10):
        text = f"{title}: {message}" if title else message
        from nicegui import Client, ui
        for client in list(Client.instances.values()):
            with client:
                ui.notify(text, timeout=duration * 1000)
