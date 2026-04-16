from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class WebsocketStatusAdapter:
    """
    Mirrors WebsocketStatus - delegates all state changes to MainPanel's public API.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")
        self._manager.main_panel.update_ws(idx, status=status, topics=topics)

    def remove(self, idx: int):
        self._manager.main_panel.remove_ws(idx)
