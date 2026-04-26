from __future__ import annotations

from math import ceil, log10
from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from constants import MAX_WEBSOCKETS, WS_TOPICS_LIMIT

DIGITS = ceil(log10(WS_TOPICS_LIMIT))

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class WebsocketSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._ws_data: dict = {}

    def build(self) -> None:
        with ui.card().props("flat bordered").classes(
            "gap-1 grow shrink basis-[180px]"
        ):
            ui.label(_("gui", "websocket", "name")).classes("font-bold text-sm mb-1")
            with ui.column().classes("gap-0"):
                self._content()

    def update(
        self, idx: int, *, status: str | None = None, topics: int | None = None
    ) -> None:
        if idx not in self._ws_data:
            self._ws_data[idx] = {
                "status": _("gui", "websocket", "disconnected"),
                "topics": 0,
            }
            if status is None:
                try:
                    ws_list = self._manager._twitch.websocket.websockets
                    if idx < len(ws_list):
                        status = (
                            _("gui", "websocket", "connected")
                            if ws_list[idx].connected
                            else _("gui", "websocket", "disconnected")
                        )
                except Exception:
                    pass
        if status is not None:
            self._ws_data[idx]["status"] = status
        if topics is not None:
            self._ws_data[idx]["topics"] = topics
        self._content.refresh()

    def remove(self, idx: int) -> None:
        self._ws_data.pop(idx, None)
        self._content.refresh()

    @ui.refreshable
    def _content(self) -> None:
        for idx in range(MAX_WEBSOCKETS):
            entry = self._ws_data.get(idx)
            ws_name = _("gui", "websocket", "websocket").format(id=idx + 1)
            if entry is None:
                label_text = ws_name
            else:
                status = entry.get("status", _("gui", "websocket", "disconnected"))
                topics = entry.get("topics", 0)
                label_text = (
                    f"{ws_name}"
                    f" {status:<20}"
                    f" {topics:>{DIGITS}}/{WS_TOPICS_LIMIT}"
                )
            ui.label(label_text).classes("font-mono text-xs")
