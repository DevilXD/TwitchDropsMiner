from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from constants import State

if TYPE_CHECKING:
    from channel import Channel
    from webui.manager import WebUIManager


class ChannelsSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._channel_map: dict = {}
        self._watching_channel_iid = None
        self._selected_channel_iid = None
        self._channel_rows: list[dict] = []
        self._channel_tables: list = []

    def build(self) -> None:
        with (
            ui.card()
            .props("flat bordered id=tdm-channels-card")
            .classes(
                "flex flex-col gap-1 grow shrink basis-[300px] min-w-0 overflow-hidden"
            )
        ):
            ui.label(_("gui", "channels", "name")).classes("font-bold text-sm mb-1")
            ui.button(
                _("gui", "channels", "switch"),
                on_click=lambda: self._on_channel_switch(),
            ).props("dense").classes("mb-2 text-xs").bind_enabled_from(
                self, "_selected_channel_iid"
            )
            self._create_table()

    def clear(self) -> None:
        self._channel_map.clear()
        self._watching_channel_iid = None
        self._selected_channel_iid = None
        self._rebuild()

    def display(self, channel: "Channel", *, add: bool = False) -> None:
        iid = channel.iid
        if not add and iid not in self._channel_map:
            return
        self._channel_map[iid] = channel
        self._rebuild()

    def remove(self, channel: "Channel") -> None:
        iid = channel.iid
        self._channel_map.pop(iid, None)
        if self._watching_channel_iid == iid:
            self._watching_channel_iid = None
        if self._selected_channel_iid == iid:
            self._selected_channel_iid = None
        self._rebuild()

    def set_watching(self, channel: "Channel") -> None:
        self._watching_channel_iid = channel.iid
        self._rebuild()

    def clear_watching(self) -> None:
        self._watching_channel_iid = None
        self._rebuild()

    def get_selected(self):
        iid = self._selected_channel_iid
        if iid is None:
            return None
        return self._channel_map.get(iid)

    def clear_selection(self) -> None:
        self._selected_channel_iid = None
        for table in self._channel_tables:
            table.selected = []

    def _rebuild(self) -> None:
        self._build_rows()
        selected = [
            r for r in self._channel_rows if r["iid"] == self._selected_channel_iid
        ]
        for table in self._channel_tables:
            table.rows = self._channel_rows
            table.selected = selected
            table.update()

    def _build_rows(self) -> None:
        self._channel_rows.clear()
        for iid, channel in self._channel_map.items():
            if channel.online:
                status = _("gui", "channels", "online")
            elif channel.pending_online:
                status = _("gui", "channels", "pending")
            else:
                status = _("gui", "channels", "offline")
            name = channel.name
            if iid == self._watching_channel_iid:
                name = "▶ " + name
            self._channel_rows.append(
                {
                    "iid": iid,
                    "channel": name,
                    "status": status,
                    "game": str(channel.game or ""),
                    "drops": "✔" if channel.drops_enabled else "❌",
                    "viewers": (
                        str(channel.viewers) if channel.viewers is not None else ""
                    ),
                    "acl_base": "✔" if channel.acl_based else "❌",
                }
            )

    def _create_table(self) -> None:
        columns = [
            {
                "name": "channel",
                "label": _("gui", "channels", "headings", "channel"),
                "field": "channel",
                "align": "left",
                "sortable": True,
            },
            {
                "name": "status",
                "label": _("gui", "channels", "headings", "status"),
                "field": "status",
                "align": "left",
            },
            {
                "name": "game",
                "label": _("gui", "channels", "headings", "game"),
                "field": "game",
                "align": "left",
                "sortable": True,
            },
            {
                "name": "drops",
                "label": "🎁",
                "field": "drops",
                "align": "center",
            },
            {
                "name": "viewers",
                "label": _("gui", "channels", "headings", "viewers"),
                "field": "viewers",
                "align": "right",
                "sortable": True,
            },
            {
                "name": "acl_base",
                "label": "📋",
                "field": "acl_base",
                "align": "center",
            },
        ]
        table = (
            ui.table(
                columns=columns,
                rows=self._channel_rows,
                row_key="iid",
                selection="single",
                on_select=self._on_table_selection,
            )
            .classes("w-full text-xs flex-1 overflow-y-auto min-h-0 max-h-full")
            .props("dense flat virtual-scroll")
        )
        if self._selected_channel_iid is not None:
            table.selected = [
                r for r in self._channel_rows if r["iid"] == self._selected_channel_iid
            ]
        self._channel_tables.append(table)
        ui.context.client.on_disconnect(
            lambda: (
                self._channel_tables.remove(table)
                if table in self._channel_tables
                else None
            )
        )

    def _on_channel_switch(self) -> None:
        try:
            self._manager._twitch.state_change(State.CHANNEL_SWITCH)()
        except Exception as e:
            print(f"Channel switch error: {e}")

    def _on_table_selection(self, e) -> None:
        selected = e.sender.selected
        self._selected_channel_iid = selected[0].get("iid") if selected else None
        for table in self._channel_tables:
            table.selected = selected
