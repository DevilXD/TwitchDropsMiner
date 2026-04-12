from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class MockStatus:
    """Mirrors StatusBar - updates the status card label"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def update(self, text: str):
        self._manager._main_panel._status_text = text  # persists for late-joining clients
        self._manager._main_panel.flush_status(text)

    def clear(self):
        self.update("")
