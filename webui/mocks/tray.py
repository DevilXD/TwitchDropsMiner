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
        
        notification_js = """
            if ("Notification" in window) {
                if (Notification.permission === "granted") {
                    new Notification(title, { body: message, icon: "/static/icon.png" });
                } else if (Notification.permission !== "denied") {
                    Notification.requestPermission().then(function (permission) {
                        if (permission === "granted") {
                            new Notification(title, { body: message, icon: "/static/icon.png" });
                        }
                    });
                }
            }
        """
        
        for client in list(Client.instances.values()):
            with client:
                ui.notify(text, timeout=duration * 1000)
                ui.run_javascript(notification_js, args={"title": title or "Twitch Drops Miner", "message": message})
