from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from .base_panel import BasePanel
from .main import (
    ChannelsSection,
    ConsoleSection,
    DropSection,
    LoginSection,
    WebsocketSection,
)

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class MainPanel(BasePanel):
    def __init__(self, manager: "WebUIManager") -> None:
        super().__init__(manager)
        self._ws_section = WebsocketSection(manager)
        self._login_section = LoginSection(manager)
        self._drop_section = DropSection(manager)
        self._console_section = ConsoleSection()
        self._channels_section = ChannelsSection(manager)

    def build(self) -> None:
        manager = self._manager

        with ui.column().classes("w-full gap-2"):
            with ui.row().classes("w-full gap-2 items-stretch flex-wrap"):
                with (
                    ui.column()
                    .classes("gap-2 grow shrink basis-[300px] min-w-0")
                    .props("id=tdm-left-col")
                ):
                    with ui.card().props("flat bordered").classes("w-full"):
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.label(_("gui", "status", "name") + ":").classes(
                                "font-bold text-sm"
                            )
                            ui.label().classes("text-sm flex-1").bind_text_from(
                                manager, "_status_text"
                            )

                    with ui.row().classes("w-full gap-2 items-stretch flex-wrap"):
                        self._ws_section.build()
                        self._login_section.build()

                    self._drop_section.build()
                    self._console_section.build()

                self._channels_section.build()

    # -------------------------------------------------------------------------
    # Console Section
    # -------------------------------------------------------------------------

    def push_console(self, lines: list) -> None:
        self._console_section.push(lines)

    # -------------------------------------------------------------------------
    # Login Section
    # -------------------------------------------------------------------------

    def update_login(self, status: str, user_id: int | None) -> None:
        self._login_section.update(status, user_id)

    # -------------------------------------------------------------------------
    # Websocket Section
    # -------------------------------------------------------------------------

    def update_ws(
        self, idx: int, *, status: str | None = None, topics: int | None = None
    ) -> None:
        self._ws_section.update(idx, status=status, topics=topics)

    def remove_ws(self, idx: int) -> None:
        self._ws_section.remove(idx)

    # -------------------------------------------------------------------------
    # Drop Section
    # -------------------------------------------------------------------------

    def clear_drop(self) -> None:
        self._drop_section.clear()

    def display_drop(
        self, drop, *, countdown: bool = True, subone: bool = False
    ) -> None:
        self._drop_section.display(drop, countdown=countdown, subone=subone)

    def drop_stop_countdown(self) -> None:
        self._drop_section.stop_countdown()

    def drop_minute_almost_done(self) -> bool:
        return self._drop_section.minute_almost_done()

    # -------------------------------------------------------------------------
    # Channels Section
    # -------------------------------------------------------------------------

    def clear_channels(self) -> None:
        self._channels_section.clear()

    def display_channel(self, channel, *, add: bool = False) -> None:
        self._channels_section.display(channel, add=add)

    def remove_channel(self, channel) -> None:
        self._channels_section.remove(channel)

    def set_watching_channel(self, channel) -> None:
        self._channels_section.set_watching(channel)

    def clear_watching_channel(self) -> None:
        self._channels_section.clear_watching()

    def get_selected_channel(self):
        return self._channels_section.get_selected()

    def clear_selection(self) -> None:
        self._channels_section.clear_selection()
