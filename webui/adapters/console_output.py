from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class ConsoleOutputAdapter:
    """Mirrors ConsoleOutput"""

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def print(self, message: str):
        self._manager.print(message)
