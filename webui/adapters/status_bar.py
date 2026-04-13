from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class StatusBarAdapter:
    """Mirrors StatusBar - delegates to manager to update both panels"""

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def update(self, text: str):
        # Manager owns the status and notifies both panels
        self._manager.update_status(text)

    def clear(self):
        self.update("")
