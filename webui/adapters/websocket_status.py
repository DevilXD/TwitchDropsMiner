from __future__ import annotations

from typing import TYPE_CHECKING

from translate import _

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class WebsocketStatusAdapter:
    """
    Mirrors WebsocketStatus - stores per-websocket data on the manager
    and schedules a UI rebuild on the NiceGUI event loop.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")
        data = self._manager.main_panel._ws_data
        if idx not in data:
            data[idx] = {
                "status": _("gui", "websocket", "disconnected"),
                "topics": 0,
            }
            # If no status was provided for a new entry, check the live websocket
            # state so already-connected sockets aren't stuck on the "Disconnected" fallback.
            if status is None:
                try:
                    ws_list = self._manager._twitch.websocket.websockets
                    if idx < len(ws_list):
                        live_status = (
                            _("gui", "websocket", "connected")
                            if ws_list[idx].connected
                            else _("gui", "websocket", "disconnected")
                        )
                        data[idx]["status"] = live_status
                except Exception:
                    pass
        if status is not None:
            data[idx]["status"] = status
        if topics is not None:
            data[idx]["topics"] = topics
        self._manager.rebuild_ws()

    def remove(self, idx: int):
        self._manager.main_panel._ws_data.pop(idx, None)
        self._manager.rebuild_ws()
