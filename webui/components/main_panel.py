# Main panel — mirrors gui.py's main tab exactly.
# Shared state (channel map, drop, ws data, login state) lives on this object.
# Bound attrs propagate to all clients automatically. The channel table uses
# per-client ui.table instances updated via .rows/.selected + .update().

from __future__ import annotations

from math import ceil, log10
from time import monotonic
from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from constants import MAX_WEBSOCKETS, WS_TOPICS_LIMIT, COOKIES_PATH, CONFIG_PATH, State
from .base_panel import BasePanel

DIGITS = ceil(log10(WS_TOPICS_LIMIT))

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class MainPanel(BasePanel):
    """
    Owns all mutable state for the main tab.

    One instance lives on WebUIManager. Each browser client calls build(),
    which registers that client's call sites for all @ui.refreshable methods.
    Shared state lives directly on this object; bound attrs propagate to all
    clients automatically, and .refresh() rebuilds structural content for all.
    """

    def __init__(self, manager: "WebUIManager") -> None:
        super().__init__(manager)
        # Shared state
        self._ws_data: dict = {}  # idx -> {status, topics}
        self._login_status_text: str = f"{_('gui', 'login', 'logged_out')}\n-"
        self._login_btn_visible: bool = False
        self._logout_btn_visible: bool = False
        self._channel_map: dict = {}  # iid -> Channel
        self._watching_channel_iid = None
        self._selected_channel_iid = None
        self._channel_rows: list[dict] = []  # shared row state for all clients
        self._channel_tables: list = []  # one ui.table per connected client

        # Drop / campaign state - Not directly bound to UI
        self._current_drop = None
        self._countdown_active: bool = False
        self._progress_seconds: int = 0
        self._countdown_start_time: float | None = None

        # Drop / campaign display state - bound to UI labels and bars
        self._campaign_game_text: str = "..."
        self._campaign_name_text: str = "..."
        self._campaign_progress_value: float = 0.0
        self._campaign_percentage_text: str = "-%"
        self._campaign_remaining_text: str = ""
        self._drop_rewards_text: str = "..."
        self._drop_progress_value: float = 0.0
        self._drop_percentage_text: str = "-%"
        self._drop_remaining_text: str = ""

        self._console_log_path = CONFIG_PATH / "console.log"
        self._console_log: list[str] = self._load_console_log()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def build(self) -> None:
        """Build the main panel UI for the current NiceGUI client."""
        self._create_panel()

    def update_ws(
        self, idx: int, *, status: str | None = None, topics: int | None = None
    ) -> None:
        """Update a websocket entry and refresh the display."""
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
        self._ws_status_content.refresh()

    def remove_ws(self, idx: int) -> None:
        """Remove a websocket entry and refresh the display."""
        self._ws_data.pop(idx, None)
        self._ws_status_content.refresh()

    def push_console(self, lines: list) -> None:
        """Refresh the console display on all connected clients."""
        self._console_log.extend(lines)
        if len(self._console_log) > 200:
            del self._console_log[:-200]
        self._save_console_log(lines)
        self._console_content.refresh()

    def clear_drop(self) -> None:
        """Clear the drop display — bound attrs propagate to all connected clients."""
        self._current_drop = None
        self._countdown_active = False
        self._countdown_start_time = None
        self._progress_seconds = 0
        self._do_clear_drop()

    def display_drop(
        self, drop, *, countdown: bool = True, subone: bool = False
    ) -> None:
        """Display current drop/campaign progress — bound attrs propagate to all clients.
        Mirrors CampaignProgress.display() exactly."""
        if drop is None:
            self.clear_drop()
            return
        self._current_drop = drop
        if countdown:
            self._countdown_active = True
            self._countdown_start_time = monotonic()
            self._progress_seconds = 60
        elif subone:
            self._countdown_active = False
            self._countdown_start_time = None
            self._progress_seconds = 0
        else:
            self._countdown_active = False
            self._countdown_start_time = None
            self._progress_seconds = 60
        self._do_display_drop(drop)
        self._tick()

    def clear_channels(self) -> None:
        """Clear all channels and rebuild the table."""
        self._channel_map.clear()
        self._watching_channel_iid = None
        self._selected_channel_iid = None
        self._rebuild_channel_table()

    def display_channel(self, channel, *, add: bool = False) -> None:
        """Add or update a channel entry, then rebuild the table."""
        iid = channel.iid
        if not add and iid not in self._channel_map:
            return
        self._channel_map[iid] = channel
        self._rebuild_channel_table()

    def remove_channel(self, channel) -> None:
        """Remove a channel entry, then rebuild the table."""
        iid = channel.iid
        self._channel_map.pop(iid, None)
        if self._watching_channel_iid == iid:
            self._watching_channel_iid = None
        if self._selected_channel_iid == iid:
            self._selected_channel_iid = None
        self._rebuild_channel_table()

    def set_watching_channel(self, channel) -> None:
        """Mark a channel as currently being watched, then rebuild the table."""
        self._watching_channel_iid = channel.iid
        self._rebuild_channel_table()

    def clear_watching_channel(self) -> None:
        """Clear the watching marker, then rebuild the table."""
        self._watching_channel_iid = None
        self._rebuild_channel_table()

    def get_selected_channel(self):
        """Return the currently selected Channel, or None."""
        iid = self._selected_channel_iid
        if iid is None:
            return None
        return self._channel_map.get(iid)

    def clear_selection(self) -> None:
        """Clear channel table selection on all clients."""
        self._selected_channel_iid = None
        for table in self._channel_tables:
            table.selected = []

    # -------------------------------------------------------------------------
    # Private — console persistence
    # -------------------------------------------------------------------------

    def _load_console_log(self) -> list[str]:
        try:
            lines = self._console_log_path.read_text(encoding="utf-8").splitlines()
            return lines[-200:]
        except (FileNotFoundError, OSError):
            return []

    def _save_console_log(self, lines: list[str]) -> None:
        try:
            CONFIG_PATH.mkdir(parents=True, exist_ok=True)
            with self._console_log_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass

    # -------------------------------------------------------------------------
    # Private — UI creation
    # -------------------------------------------------------------------------

    def _create_panel(self) -> None:
        """Build all widgets for this client."""
        manager = self._manager

        with ui.column().classes("w-full gap-2"):
            with ui.row().classes("w-full gap-2 items-stretch flex-wrap"):
                # Left column
                with (
                    ui.column()
                    .classes("gap-2 grow shrink basis-[300px] min-w-0")
                    .props("id=tdm-left-col")
                ):
                    # Status Bar — matches StatusBar class
                    with ui.card().props("flat bordered").classes("w-full"):
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.label(_("gui", "status", "name") + ":").classes(
                                "font-bold text-sm"
                            )
                            ui.label().classes("text-sm flex-1").bind_text_from(
                                manager, "_status_text"
                            )

                    # WebSocket Status + Login side by side
                    with ui.row().classes("w-full gap-2 items-stretch flex-wrap"):
                        # WebSocket Status — matches WebsocketStatus class
                        with (
                            ui.card()
                            .props("flat bordered")
                            .classes("gap-1 grow shrink basis-[180px]")
                        ):
                            ui.label(_("gui", "websocket", "name")).classes(
                                "font-bold text-sm mb-1"
                            )
                            with ui.column().classes("gap-0"):
                                self._ws_status_content()

                        # Login Form — matches LoginForm class
                        with (
                            ui.card()
                            .props("flat bordered")
                            .classes("gap-1 grow shrink basis-[180px]")
                        ):
                            ui.label(_("gui", "login", "name")).classes(
                                "font-bold text-sm mb-1"
                            )
                            with ui.row().classes("gap-4 items-start"):
                                ui.label(_("gui", "login", "labels")).classes(
                                    "text-xs whitespace-pre leading-relaxed"
                                )
                                ui.label().classes(
                                    "text-xs whitespace-pre leading-relaxed"
                                ).bind_text_from(self, "_login_status_text")
                            (
                                ui.button(
                                    _("gui", "login", "button"),
                                    on_click=manager.login.open_login_popup,
                                )
                                .props("dense")
                                .classes("text-xs")
                                .bind_visibility_from(self, "_login_btn_visible")
                            )
                            (
                                ui.button(
                                    "Logout",
                                    on_click=lambda: self._on_logout(),
                                )
                                .props("dense")
                                .classes("text-xs")
                                .bind_visibility_from(self, "_logout_btn_visible")
                            )

                    # Campaign Progress — matches CampaignProgress class
                    with ui.card().props("flat bordered").classes("w-full gap-1"):
                        ui.label(_("gui", "progress", "name")).classes(
                            "font-bold text-sm mb-1"
                        )
                        with ui.grid(columns=2).classes("w-full text-xs gap-1"):
                            ui.label(_("gui", "progress", "game")).classes("font-bold")
                            ui.label(_("gui", "progress", "campaign")).classes(
                                "font-bold"
                            )
                            ui.label().bind_text_from(self, "_campaign_game_text")
                            ui.label().bind_text_from(self, "_campaign_name_text")
                        ui.label(_("gui", "progress", "campaign_progress")).classes(
                            "text-xs font-bold"
                        )
                        with ui.row().classes("w-full gap-2 items-center text-xs"):
                            ui.label().classes("w-24").bind_text_from(
                                self, "_campaign_percentage_text"
                            )
                            ui.label().classes("flex-1").bind_text_from(
                                self, "_campaign_remaining_text"
                            )
                        ui.linear_progress(value=0, show_value=False).classes(
                            "w-full h-4"
                        ).bind_value_from(self, "_campaign_progress_value")
                        ui.separator().classes("my-1")
                        ui.label(_("gui", "progress", "drop")).classes(
                            "text-xs font-bold"
                        )
                        ui.label().classes("text-xs").bind_text_from(
                            self, "_drop_rewards_text"
                        )
                        ui.label(_("gui", "progress", "drop_progress")).classes(
                            "text-xs font-bold"
                        )
                        with ui.row().classes("w-full gap-2 items-center text-xs"):
                            ui.label().classes("w-24").bind_text_from(
                                self, "_drop_percentage_text"
                            )
                            ui.label().classes("flex-1").bind_text_from(
                                self, "_drop_remaining_text"
                            )
                        ui.linear_progress(value=0, show_value=False).classes(
                            "w-full h-4"
                        ).bind_value_from(self, "_drop_progress_value")

                    # Console Output — matches ConsoleOutput class
                    with ui.card().props("flat bordered").classes("w-full gap-1"):
                        ui.label(_("gui", "output")).classes("font-bold text-sm mb-1")
                        self._console_content()

                # Right side: Channel List — matches ChannelList class
                with (
                    ui.card()
                    .props("flat bordered id=tdm-channels-card")
                    .classes(
                        "flex flex-col gap-1 grow shrink basis-[300px] min-w-0 overflow-hidden"
                    )
                ):
                    ui.label(_("gui", "channels", "name")).classes(
                        "font-bold text-sm mb-1"
                    )
                    ui.button(
                        _("gui", "channels", "switch"),
                        on_click=lambda: self._on_channel_switch(),
                    ).props("dense").classes("mb-2 text-xs").bind_enabled_from(
                        self, "_selected_channel_iid"
                    )
                    self._create_channel_table()

        timer = ui.timer(1.0, self._tick)
        ui.context.client.on_disconnect(lambda: timer.cancel())

    # -------------------------------------------------------------------------
    # Private — refreshable content methods
    # -------------------------------------------------------------------------

    @ui.refreshable
    def _ws_status_content(self) -> None:
        """Refreshable content for the WebSocket status display."""
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

    @ui.refreshable
    def _console_content(self) -> None:
        """Refreshable console log — rebuilt from the full log on each push."""
        log = ui.log(max_lines=200).classes("h-64 w-full font-mono text-xs")
        for line in self._console_log:
            log.push(line)

    def _rebuild_channel_table(self) -> None:
        """Push updated rows and selection to all connected client tables."""
        self._build_channel_rows()
        selected = [
            r for r in self._channel_rows if r["iid"] == self._selected_channel_iid
        ]
        for table in self._channel_tables:
            table.rows = self._channel_rows
            table.selected = selected
            table.update()

    def _build_channel_rows(self) -> None:
        """Rebuild _channel_rows in-place from _channel_map."""
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

    def _create_channel_table(self) -> None:
        """Create the channel table for this client and register it for live updates."""
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

    def _do_display_drop(self, drop) -> None:
        """Update drop/campaign display attrs — bindings propagate to all clients."""
        campaign = drop.campaign
        self._campaign_game_text = campaign.game.name
        self._campaign_name_text = campaign.name
        self._campaign_progress_value = campaign.progress
        self._campaign_percentage_text = f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
        self._drop_rewards_text = drop.rewards_text()
        self._drop_progress_value = drop.progress
        self._drop_percentage_text = f"{drop.progress:6.1%}"

    def _do_clear_drop(self) -> None:
        """Reset drop/campaign display attrs — bindings propagate to all clients."""
        self._campaign_game_text = "..."
        self._campaign_name_text = "..."
        self._campaign_progress_value = 0.0
        self._campaign_percentage_text = "-%"
        self._campaign_remaining_text = ""
        self._drop_rewards_text = "..."
        self._drop_progress_value = 0.0
        self._drop_percentage_text = "-%"
        self._drop_remaining_text = ""

    def _tick(self) -> None:
        """Update remaining-time attrs — bindings propagate to all clients."""
        drop = self._current_drop
        if drop is None:
            return
        if self._countdown_active and self._countdown_start_time is not None:
            elapsed = int(monotonic() - self._countdown_start_time)
            self._progress_seconds = max(0, 60 - elapsed)
        secs = self._progress_seconds % 60

        drop_mins = drop.remaining_minutes
        if self._progress_seconds < 60 and drop_mins > 0:
            drop_mins -= 1
        h, m = divmod(drop_mins, 60)
        self._drop_remaining_text = _("gui", "progress", "remaining").format(
            time=f"{h:>2}:{m:02}:{secs:02}"
        )

        camp_mins = drop.campaign.remaining_minutes
        if self._progress_seconds < 60 and camp_mins > 0:
            camp_mins -= 1
        h, m = divmod(camp_mins, 60)
        self._campaign_remaining_text = _("gui", "progress", "remaining").format(
            time=f"{h:>2}:{m:02}:{secs:02}"
        )

    # -------------------------------------------------------------------------
    # Private — event handlers
    # -------------------------------------------------------------------------

    def _on_channel_switch(self) -> None:
        try:
            self._manager._twitch.state_change(State.CHANNEL_SWITCH)()
        except Exception as e:
            print(f"Channel switch error: {e}")

    def _on_table_selection(self, e) -> None:
        """Handle row selection: sync selection to all client tables."""
        selected = e.sender.selected
        self._selected_channel_iid = selected[0].get("iid") if selected else None
        for table in self._channel_tables:
            table.selected = selected

    def _on_logout(self) -> None:
        try:
            manager = self._manager
            COOKIES_PATH.unlink(missing_ok=True)
            if manager._twitch._session is not None:
                manager._twitch._session.cookie_jar.clear()
            manager._twitch._auth_state.clear()
            manager.channels.clear()
            manager.inv.clear()
            manager._twitch.stop_watching()
            self._ws_data.clear()
            self._ws_status_content.refresh()
            manager.login.update(_("gui", "login", "logged_out"), None)
            manager.status.update(_("gui", "login", "request"))
            manager._twitch.state_change(State.INVENTORY_FETCH)()
        except Exception as e:
            print(f"Logout error: {e}")
