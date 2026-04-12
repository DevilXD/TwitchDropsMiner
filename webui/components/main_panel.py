# Main panel — mirrors gui.py's main tab exactly.
# All widget refs are stored per-client in _client_widgets so multiple browser
# tabs stay in sync. Shared state (channel map, drop, ws data, login state)
# lives on WebUIManager and is read by the per-widget helpers here.

from __future__ import annotations

from math import ceil, log10
from time import monotonic
from typing import TYPE_CHECKING

try:
    from nicegui import ui
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

from translate import _
from constants import MAX_WEBSOCKETS, WS_TOPICS_LIMIT
from webui.thread_utils import call_on_main_loop
from .base_panel import BasePanel

DIGITS = ceil(log10(WS_TOPICS_LIMIT))

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class MainPanel(BasePanel):
    """
    Owns all widget references and mutable state for the main tab.

    One instance lives on WebUIManager. Each browser client calls build(),
    which creates that client's widgets and stores refs in _client_widgets
    keyed by client ID. Shared state (channel map, drop progress, ws data,
    login state) lives on WebUIManager and is read by the helpers here.
    """

    def __init__(self, manager: 'WebUIManager') -> None:
        super().__init__(manager)
        # Per-client widget refs (keyed by NiceGUI client ID)
        self._client_widgets: dict = {}

        # Shared state — persisted so late-joining clients start in sync
        self._status_text: str = "Initializing..."
        self._ws_data: dict = {}                    # idx -> {status, topics}
        self._login_status_text: str = (
            f"{_('gui', 'login', 'logged_out')}\n-"
        )
        self._login_btn_visible: bool = False
        self._logout_btn_visible: bool = False
        self._channel_map: dict = {}                # iid -> Channel
        self._watching_channel_iid = None
        self._selected_channel_iid = None
        self._current_drop = None
        self._countdown_active: bool = False
        self._progress_seconds: int = 0
        self._countdown_start_time: float | None = None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def build(self) -> None:
        """Build the main panel UI for the current NiceGUI client."""
        if not NICEGUI_AVAILABLE:
            return
        client_id = ui.context.client.id
        widgets: dict = {}
        self._client_widgets[client_id] = widgets
        ui.context.client.on_disconnect(lambda: self._client_widgets.pop(client_id, None))
        self._create_panel(client_id, widgets)
        self._flush_state(widgets)

    def register_header_label(self, client_id: str, label) -> None:
        """Register the header status label created in manager._setup_ui.
        Called after build() so the client entry already exists."""
        w = self._client_widgets.get(client_id)
        if w is not None:
            w['status_label'] = label
            label.set_text(self._status_text)

    def flush_login(self) -> None:
        """Push current login state to all connected clients."""
        for w in self._client_widgets.values():
            if w.get('login_status_label') is not None:
                w['login_status_label'].set_text(self._login_status_text)
            if w.get('login_button') is not None:
                w['login_button'].set_visibility(self._login_btn_visible)
            if w.get('logout_button') is not None:
                w['logout_button'].set_visibility(self._logout_btn_visible)

    def flush_status(self, text: str) -> None:
        """Push status text to all connected clients (header + status card)."""
        for w in self._client_widgets.values():
            if w.get('status_label') is not None:
                w['status_label'].set_text(text)
            if w.get('status_card') is not None:
                w['status_card'].set_text(text)

    def rebuild_channel_table(self) -> None:
        """Rebuild channel table rows on all connected clients."""
        for w in self._client_widgets.values():
            self._do_rebuild_channel_table(w)

    def rebuild_ws(self) -> None:
        """Rebuild websocket status rows on all connected clients."""
        for w in self._client_widgets.values():
            self._do_rebuild_ws(w)

    def push_console(self, lines: list) -> None:
        """Push new log lines to all connected clients' consoles."""
        for w in self._client_widgets.values():
            console = w.get('console')
            if console is not None:
                for line in lines:
                    console.push(line)

    def clear_drop(self) -> None:
        """Clear the drop display on all connected clients."""
        self._current_drop = None
        self._countdown_active = False
        self._countdown_start_time = None
        self._progress_seconds = 0
        for w in self._client_widgets.values():
            self._do_clear_drop(w)

    def display_drop(self, drop, *, countdown: bool = True, subone: bool = False) -> None:
        """Display current drop/campaign progress on all connected clients.
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
        for w in self._client_widgets.values():
            self._do_display_drop(w, drop)
            self._do_tick_progress(w)

    def clear_selection(self) -> None:
        """Clear channel table selection and disable the Switch button on all clients."""
        for w in self._client_widgets.values():
            table = w.get('channels_table')
            if table is not None:
                table.selected.clear()
                table.update()
            btn = w.get('channel_switch_btn')
            if btn is not None:
                btn.props('disabled')

    def tick(self, client_id: str) -> None:
        """Per-client 1-second timer tick — updates only this client's labels."""
        w = self._client_widgets.get(client_id)
        if w is not None:
            self._do_tick_progress(w)

    # -------------------------------------------------------------------------
    # Private — UI creation
    # -------------------------------------------------------------------------

    def _create_panel(self, client_id: str, widgets: dict) -> None:
        """Build all widgets for one client and store refs in widgets."""
        manager = self._manager

        with ui.column().classes('w-full gap-2'):
            with ui.row().classes('w-full gap-2 items-stretch flex-wrap'):

                # Left column
                with ui.column().classes('gap-2 grow shrink basis-[300px] min-w-0').props('id=tdm-left-col'):

                    # Status Bar — matches StatusBar class
                    with ui.card().props('flat bordered').classes('w-full'):
                        with ui.row().classes('items-center gap-2 w-full'):
                            ui.label(_("gui", "status", "name") + ":").classes('font-bold text-sm')
                            widgets['status_card'] = ui.label("Initializing...").classes('text-sm flex-1')

                    # WebSocket Status + Login side by side
                    with ui.row().classes('w-full gap-2 items-stretch flex-wrap'):

                        # WebSocket Status — matches WebsocketStatus class
                        with ui.card().props('flat bordered').classes('gap-1 grow shrink basis-[180px]'):
                            ui.label(_("gui", "websocket", "name")).classes('font-bold text-sm mb-1')
                            widgets['ws_container'] = ui.column().classes('gap-0')
                            self._do_rebuild_ws(widgets)

                        # Login Form — matches LoginForm class
                        with ui.card().props('flat bordered').classes('gap-1 grow shrink basis-[180px]'):
                            ui.label(_("gui", "login", "name")).classes('font-bold text-sm mb-1')
                            with ui.row().classes('gap-4 items-start'):
                                ui.label(_("gui", "login", "labels")).classes(
                                    'text-xs whitespace-pre leading-relaxed'
                                )
                                widgets['login_status_label'] = ui.label(
                                    f"{_('gui', 'login', 'logged_out')}\n-"
                                ).classes('text-xs whitespace-pre leading-relaxed')
                            widgets['login_button'] = ui.button(
                                _("gui", "login", "button"),
                                on_click=lambda: call_on_main_loop(manager.login, manager.login._confirm.set),
                            ).props('dense').classes('text-xs')
                            widgets['login_button'].set_visibility(False)
                            widgets['logout_button'] = ui.button(
                                "Logout",
                                on_click=lambda: self._on_logout(),
                            ).props('dense').classes('text-xs')
                            widgets['logout_button'].set_visibility(False)

                    # Campaign Progress — matches CampaignProgress class
                    with ui.card().props('flat bordered').classes('w-full gap-1'):
                        ui.label(_("gui", "progress", "name")).classes('font-bold text-sm mb-1')
                        with ui.grid(columns=2).classes('w-full text-xs gap-1'):
                            ui.label(_("gui", "progress", "game")).classes('font-bold')
                            ui.label(_("gui", "progress", "campaign")).classes('font-bold')
                            widgets['campaign_game_label'] = ui.label("...")
                            widgets['campaign_name_label'] = ui.label("...")
                        ui.label(_("gui", "progress", "campaign_progress")).classes('text-xs font-bold')
                        with ui.row().classes('w-full gap-2 items-center text-xs'):
                            widgets['campaign_percentage_label'] = ui.label("-%").classes('w-24')
                            widgets['campaign_remaining_label'] = ui.label("").classes('flex-1')
                        widgets['campaign_progress_bar'] = ui.linear_progress(
                            value=0, show_value=False
                        ).classes('w-full h-4')
                        ui.separator().classes('my-1')
                        ui.label(_("gui", "progress", "drop")).classes('text-xs font-bold')
                        widgets['drop_rewards_label'] = ui.label("...").classes('text-xs')
                        ui.label(_("gui", "progress", "drop_progress")).classes('text-xs font-bold')
                        with ui.row().classes('w-full gap-2 items-center text-xs'):
                            widgets['drop_percentage_label'] = ui.label("-%").classes('w-24')
                            widgets['drop_remaining_label'] = ui.label("").classes('flex-1')
                        widgets['drop_progress_bar'] = ui.linear_progress(
                            value=0, show_value=False
                        ).classes('w-full h-4')

                    # Console Output — matches ConsoleOutput class
                    with ui.card().props('flat bordered').classes('w-full gap-1'):
                        ui.label(_("gui", "output")).classes('font-bold text-sm mb-1')
                        widgets['console'] = ui.log(max_lines=200).classes(
                            'h-64 w-full font-mono text-xs'
                        )

                # Right side: Channel List — matches ChannelList class
                with ui.card().props('flat bordered id=tdm-channels-card').classes(
                    'flex flex-col gap-1 grow shrink basis-[300px] min-w-0 overflow-hidden'
                ):
                    ui.label(_("gui", "channels", "name")).classes('font-bold text-sm mb-1')
                    widgets['channel_switch_btn'] = ui.button(
                        _("gui", "channels", "switch"),
                        on_click=lambda: self._on_channel_switch(),
                    ).props('disabled dense').classes('mb-2 text-xs')

                    columns = [
                        {
                            'name': 'channel',
                            'label': _("gui", "channels", "headings", "channel"),
                            'field': 'channel',
                            'align': 'left',
                            'sortable': True,
                        },
                        {
                            'name': 'status',
                            'label': _("gui", "channels", "headings", "status"),
                            'field': 'status',
                            'align': 'left',
                        },
                        {
                            'name': 'game',
                            'label': _("gui", "channels", "headings", "game"),
                            'field': 'game',
                            'align': 'left',
                            'sortable': True,
                        },
                        {
                            'name': 'drops',
                            'label': '🎁',
                            'field': 'drops',
                            'align': 'center',
                        },
                        {
                            'name': 'viewers',
                            'label': _("gui", "channels", "headings", "viewers"),
                            'field': 'viewers',
                            'align': 'right',
                            'sortable': True,
                        },
                        {
                            'name': 'acl_base',
                            'label': '📋',
                            'field': 'acl_base',
                            'align': 'center',
                        },
                    ]
                    table = ui.table(
                        columns=columns,
                        rows=[],
                        row_key='iid',
                        selection='single',
                    ).classes('w-full text-xs flex-1 overflow-y-auto min-h-0 max-h-full').props(
                        'dense flat virtual-scroll'
                    )
                    widgets['channels_table'] = table
                    table.on('selection', lambda e, cid=client_id: self._on_table_selection(cid, e))

        ui.timer(1.0, lambda: self.tick(client_id))

    # -------------------------------------------------------------------------
    # Private — state flush
    # -------------------------------------------------------------------------

    def _flush_state(self, widgets: dict) -> None:
        """Populate freshly-created widgets with current state so clients
        connecting after initialization see correct values immediately."""
        if widgets.get('status_card') is not None:
            widgets['status_card'].set_text(self._status_text)

        # Login state
        if widgets.get('login_status_label') is not None:
            widgets['login_status_label'].set_text(self._login_status_text)
        if widgets.get('login_button') is not None:
            widgets['login_button'].set_visibility(self._login_btn_visible)
        if widgets.get('logout_button') is not None:
            widgets['logout_button'].set_visibility(self._logout_btn_visible)

        # Channel table (ws rows already built in _create_panel)
        self._do_rebuild_channel_table(widgets)

        # Switch button state based on current selection
        btn = widgets.get('channel_switch_btn')
        if btn is not None:
            if self._selected_channel_iid is not None:
                btn.props(remove='disabled')
            else:
                btn.props('disabled')

        # Drop / campaign progress
        if self._current_drop is not None:
            self._do_display_drop(widgets, self._current_drop)
            self._do_tick_progress(widgets)

        # Replay buffered console history
        console = widgets.get('console')
        if console is not None:
            for line in self._manager._console_log:
                console.push(line)

    # -------------------------------------------------------------------------
    # Private — per-widget update helpers
    # -------------------------------------------------------------------------

    def _do_rebuild_ws(self, widgets: dict) -> None:
        container = widgets.get('ws_container')
        if container is None:
            return
        try:
            container.clear()
            with container:
                for idx in range(MAX_WEBSOCKETS):
                    entry = self._ws_data.get(idx)
                    ws_name = _('gui', 'websocket', 'websocket').format(id=idx + 1)
                    if entry is None:
                        label_text = ws_name
                    else:
                        status = entry.get('status', _("gui", "websocket", "disconnected"))
                        topics = entry.get('topics', 0)
                        label_text = (
                            f"{ws_name}"
                            f" {status:<20}"
                            f" {topics:>{DIGITS}}/{WS_TOPICS_LIMIT}"
                        )
                    ui.label(label_text).classes('font-mono text-xs')
        except Exception as e:
            print(f"Failed to rebuild WS display: {e}")

    def _do_rebuild_channel_table(self, widgets: dict) -> None:
        table = widgets.get('channels_table')
        if table is None:
            return
        rows = []
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
            rows.append({
                'iid': iid,
                'channel': name,
                'status': status,
                'game': str(channel.game or ''),
                'drops': '✔' if channel.drops_enabled else '❌',
                'viewers': str(channel.viewers) if channel.viewers is not None else '',
                'acl_base': '✔' if channel.acl_based else '❌',
            })
        # Preserve the selected row if it still exists in the new rows
        if self._selected_channel_iid is not None:
            table.selected = [r for r in rows if r['iid'] == self._selected_channel_iid]
        table.rows = rows
        table.update()

    def _do_display_drop(self, widgets: dict, drop) -> None:
        try:
            campaign = drop.campaign
            if widgets.get('campaign_game_label') is not None:
                widgets['campaign_game_label'].set_text(campaign.game.name)
            if widgets.get('campaign_name_label') is not None:
                widgets['campaign_name_label'].set_text(campaign.name)
            if widgets.get('campaign_progress_bar') is not None:
                widgets['campaign_progress_bar'].set_value(campaign.progress)
            if widgets.get('campaign_percentage_label') is not None:
                widgets['campaign_percentage_label'].set_text(
                    f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
                )
            if widgets.get('drop_rewards_label') is not None:
                widgets['drop_rewards_label'].set_text(drop.rewards_text())
            if widgets.get('drop_progress_bar') is not None:
                widgets['drop_progress_bar'].set_value(drop.progress)
            if widgets.get('drop_percentage_label') is not None:
                widgets['drop_percentage_label'].set_text(f"{drop.progress:6.1%}")
        except Exception as e:
            print(f"Failed to display drop: {e}")

    def _do_clear_drop(self, widgets: dict) -> None:
        try:
            if widgets.get('drop_rewards_label') is not None:
                widgets['drop_rewards_label'].set_text("...")
            if widgets.get('drop_progress_bar') is not None:
                widgets['drop_progress_bar'].set_value(0)
            if widgets.get('drop_percentage_label') is not None:
                widgets['drop_percentage_label'].set_text("-%")
            if widgets.get('drop_remaining_label') is not None:
                widgets['drop_remaining_label'].set_text("")
            if widgets.get('campaign_name_label') is not None:
                widgets['campaign_name_label'].set_text("...")
            if widgets.get('campaign_game_label') is not None:
                widgets['campaign_game_label'].set_text("...")
            if widgets.get('campaign_progress_bar') is not None:
                widgets['campaign_progress_bar'].set_value(0)
            if widgets.get('campaign_percentage_label') is not None:
                widgets['campaign_percentage_label'].set_text("-%")
            if widgets.get('campaign_remaining_label') is not None:
                widgets['campaign_remaining_label'].set_text("")
        except Exception as e:
            print(f"Failed to clear drop: {e}")

    def _do_tick_progress(self, widgets: dict) -> None:
        """Update remaining-time labels for one client using real elapsed time."""
        drop = self._current_drop
        if drop is None:
            return
        if self._countdown_active and self._countdown_start_time is not None:
            elapsed = int(monotonic() - self._countdown_start_time)
            self._progress_seconds = max(0, 60 - elapsed)
        secs = self._progress_seconds % 60

        if widgets.get('drop_remaining_label') is not None:
            try:
                drop_mins = drop.remaining_minutes
                if self._progress_seconds < 60 and drop_mins > 0:
                    drop_mins -= 1
                h, m = divmod(drop_mins, 60)
                widgets['drop_remaining_label'].set_text(
                    _("gui", "progress", "remaining").format(time=f"{h:>2}:{m:02}:{secs:02}")
                )
            except Exception:
                pass

        if widgets.get('campaign_remaining_label') is not None:
            try:
                camp_mins = drop.campaign.remaining_minutes
                if self._progress_seconds < 60 and camp_mins > 0:
                    camp_mins -= 1
                h, m = divmod(camp_mins, 60)
                widgets['campaign_remaining_label'].set_text(
                    _("gui", "progress", "remaining").format(time=f"{h:>2}:{m:02}:{secs:02}")
                )
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Private — event handlers
    # -------------------------------------------------------------------------

    def _on_channel_switch(self) -> None:
        try:
            from constants import State
            self._manager._twitch.state_change(State.CHANNEL_SWITCH)()
        except Exception as e:
            print(f"Channel switch error: {e}")

    def _on_table_selection(self, client_id: str, e) -> None:
        """Handle row selection: sync selection highlight and Switch button to all clients."""
        try:
            w = self._client_widgets.get(client_id)
            table = w.get('channels_table') if w else None
            selected = table.selected if table else []
            iid = selected[0].get('iid') if selected else None
            self._selected_channel_iid = iid

            for cid, cw in self._client_widgets.items():
                # Sync Switch button on every client
                btn = cw.get('channel_switch_btn')
                if btn is not None:
                    if iid is not None:
                        btn.props(remove='disabled')
                    else:
                        btn.props('disabled')

                # Sync table selection highlight on every other client
                if cid != client_id:
                    other_table = cw.get('channels_table')
                    if other_table is not None:
                        other_table.selected = (
                            [r for r in other_table.rows if r['iid'] == iid]
                            if iid is not None else []
                        )
                        other_table.update()
        except Exception as ex:
            print(f"Selection handler error: {ex}")

    def _on_logout(self) -> None:
        try:
            from constants import COOKIES_PATH, State
            manager = self._manager
            COOKIES_PATH.unlink(missing_ok=True)
            if manager._twitch._session is not None:
                manager._twitch._session.cookie_jar.clear()
            manager._twitch._auth_state.clear()
            manager.channels.clear()
            manager.inv.clear()
            manager._twitch.stop_watching()
            self._ws_data.clear()
            self.rebuild_ws()
            manager.login.update(_("gui", "login", "logged_out"), None)
            manager.status.update(_("gui", "login", "request"))
            call_on_main_loop(manager, manager._twitch.state_change(State.INVENTORY_FETCH))
        except Exception as e:
            print(f"Logout error: {e}")
