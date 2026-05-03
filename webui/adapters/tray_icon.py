from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import app, ui

from webui.html_utils import favicon_js, notification_js

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class TrayIconAdapter:
    """Mirrors TrayIcon - no-op for web UI"""

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def change_icon(self, icon_name: str):
        self._manager._current_icon = icon_name
        for client in app.clients():
            with client:
                ui.run_javascript(favicon_js(icon_name))

    def update_title(self, drop):
        pass

    def restore(self):
        pass

    def stop(self):
        pass

    def notify(self, message: str, title: str | None = None, duration: float = 10):
        text = f"{title}: {message}" if title else message
        js = notification_js(title or "Twitch Drops Miner", message)

        for client in app.clients():
            with client:
                ui.notify(text, timeout=duration * 1000)
                ui.run_javascript(js)
