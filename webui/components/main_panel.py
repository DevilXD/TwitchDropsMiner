# Main panel UI components for the WebUI
# Replicates the exact layout and behavior of gui.py's main tab

from __future__ import annotations

from math import ceil, log10
from typing import TYPE_CHECKING

try:
    from nicegui import ui
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

from translate import _
from constants import MAX_WEBSOCKETS, WS_TOPICS_LIMIT

DIGITS = ceil(log10(WS_TOPICS_LIMIT))

if TYPE_CHECKING:
    from webui.manager import WebUIManager


def create_main_panel(manager: 'WebUIManager'):
    """Create the main panel - matches gui.py's main tab layout exactly"""
    if not NICEGUI_AVAILABLE:
        return

    with ui.column().classes('w-full gap-2'):

        # Row 1: Left side (Status, WebSocket + Login, Campaign Progress, Console) and Right side (Channel List)
        with ui.row().classes('w-full gap-2 items-stretch'):

            # Left column
            with ui.column().classes('gap-2').style('flex: 1; min-width: 0').props('id=tdm-left-col'):

                # Status Bar (full width) - matches StatusBar class
                with ui.card().props('flat bordered').classes('w-full'):
                    with ui.row().classes('items-center gap-2 w-full'):
                        ui.label(_("gui", "status", "name") + ":").classes('font-bold text-sm')
                        manager._status_card = ui.label("Initializing...").classes('text-sm flex-1')

                # WebSocket Status + Login side by side - matches WebsocketStatus + LoginForm
                with ui.row().classes('w-full gap-2 items-stretch'):

                    # WebSocket Status card - matches WebsocketStatus class
                    with ui.card().props('flat bordered').classes('flex-1 gap-1'):
                        ui.label(_("gui", "websocket", "name")).classes('font-bold text-sm mb-1')
                        manager._ws_container = ui.column().classes('gap-0')
                        _build_ws_rows(manager)

                    # Login Form card - matches LoginForm class
                    with ui.card().props('flat bordered').classes('flex-1 gap-1'):
                        ui.label(_("gui", "login", "name")).classes('font-bold text-sm mb-1')
                        with ui.row().classes('gap-4 items-start'):
                            ui.label(_("gui", "login", "labels")).classes(
                                'text-xs whitespace-pre leading-relaxed'
                            )
                            manager._login_status_label = ui.label(
                                f"{_('gui', 'login', 'logged_out')}\n-"
                            ).classes('text-xs whitespace-pre leading-relaxed')
                        manager._login_button = ui.button(
                            _("gui", "login", "button"),
                            on_click=lambda: manager._main_loop.call_soon_threadsafe(
                                manager.login._confirm.set
                            )
                        ).props('dense').classes('text-xs')
                        manager._login_button.set_visibility(False)
                        manager._logout_button = ui.button(
                            "Logout",
                            on_click=lambda: _on_logout(manager)
                        ).props('dense').classes('text-xs')
                        manager._logout_button.set_visibility(False)

                # Campaign Progress card - matches CampaignProgress class
                with ui.card().props('flat bordered').classes('w-full gap-1'):
                    ui.label(_("gui", "progress", "name")).classes('font-bold text-sm mb-1')

                    # Game and Campaign name row
                    with ui.grid(columns=2).classes('w-full text-xs gap-1'):
                        ui.label(_("gui", "progress", "game")).classes('font-bold')
                        ui.label(_("gui", "progress", "campaign")).classes('font-bold')
                        manager._campaign_game_label = ui.label("...")
                        manager._campaign_name_label = ui.label("...")

                    # Campaign progress section
                    ui.label(_("gui", "progress", "campaign_progress")).classes(
                        'text-xs font-bold'
                    )
                    with ui.row().classes('w-full gap-2 items-center text-xs'):
                        manager._campaign_percentage_label = ui.label("-%").classes('w-24')
                        manager._campaign_remaining_label = ui.label("").classes('flex-1')
                    manager._campaign_progress_bar = ui.linear_progress(value=0, show_value=False).classes('w-full h-4')

                    ui.separator().classes('my-1')

                    # Drop section
                    ui.label(_("gui", "progress", "drop")).classes('text-xs font-bold')
                    manager._drop_rewards_label = ui.label("...").classes('text-xs')
                    ui.label(_("gui", "progress", "drop_progress")).classes(
                        'text-xs font-bold'
                    )
                    with ui.row().classes('w-full gap-2 items-center text-xs'):
                        manager._drop_percentage_label = ui.label("-%").classes('w-24')
                        manager._drop_remaining_label = ui.label("").classes('flex-1')
                    manager._drop_progress_bar = ui.linear_progress(value=0, show_value=False).classes('w-full h-4')

                # Console Output - matches ConsoleOutput class
                with ui.card().props('flat bordered').classes('w-full gap-1'):
                    ui.label(_("gui", "output")).classes('font-bold text-sm mb-1')
                    manager._console = ui.log(max_lines=200).classes(
                        'h-64 w-full font-mono text-xs'
                    )

            # Right side: Channel List - matches ChannelList class (spans full height)
            with ui.card().props('flat bordered id=tdm-channels-card').classes('flex-col gap-1').style('flex: 1; min-width: 0; display: flex; overflow: hidden'):
                ui.label(_("gui", "channels", "name")).classes('font-bold text-sm mb-1')

                # Switch button (disabled until a channel is selected)
                manager._channel_switch_btn = ui.button(
                    _("gui", "channels", "switch"),
                    on_click=lambda: _on_channel_switch(manager)
                ).props('disabled dense').classes('mb-2 text-xs')

                # Channel table with columns matching gui.py ChannelList
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
                manager._channels_table = ui.table(
                    columns=columns,
                    rows=[],
                    row_key='iid',
                    selection='single',
                ).classes('w-full text-xs').props('dense flat virtual-scroll').style(
                    'flex: 1; overflow-y: auto; min-height: 0; max-height: 100%;'
                )

                # Handle row selection to enable/disable Switch button
                manager._channels_table.on(
                    'selection',
                    lambda e: _on_table_selection(manager, e)
                )

    # Flush current app state into the freshly created UI elements so that
    # clients connecting after initialization see the correct values immediately.
    _flush_current_state(manager)

    # Per-client 1-second timer for countdown and dirty updates
    ui.timer(1.0, lambda: _tick_update(manager))

    # Restore any buffered console lines that arrived before the UI was ready
    for line in manager._console_log:
        manager._console.push(line)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flush_current_state(manager: 'WebUIManager'):
    """
    Populate freshly-created UI elements with the current manager state so that
    clients connecting after initialization see the correct values immediately.
    """
    # Status labels (header + status card)
    if manager._status_card is not None:
        manager._status_card.set_text(manager._status_text)
    if manager._status_label is not None:
        manager._status_label.set_text(manager._status_text)

    # Login status
    if manager._login_status_label is not None:
        manager._login_status_label.set_text(manager._login_status_text)
    if manager._login_button is not None:
        manager._login_button.set_visibility(manager._login_btn_visible)
    if manager._logout_button is not None:
        manager._logout_button.set_visibility(manager._logout_btn_visible)

    # WebSocket rows
    _build_ws_rows(manager)

    # Channel table
    _rebuild_channel_table(manager)

    # Drop / campaign progress — render stored state without touching the timer
    if manager._current_drop is not None:
        _render_drop_labels(manager)


def _render_drop_labels(manager: 'WebUIManager'):
    """Set all drop/campaign labels from the currently stored drop without altering timer state."""
    drop = manager._current_drop
    if drop is None:
        return
    try:
        campaign = drop.campaign
        if manager._campaign_game_label is not None:
            manager._campaign_game_label.set_text(campaign.game.name)
        if manager._campaign_name_label is not None:
            manager._campaign_name_label.set_text(campaign.name)
        if manager._campaign_progress_bar is not None:
            manager._campaign_progress_bar.set_value(campaign.progress)
        if manager._campaign_percentage_label is not None:
            manager._campaign_percentage_label.set_text(
                f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
            )
        if manager._drop_rewards_label is not None:
            manager._drop_rewards_label.set_text(drop.rewards_text())
        if manager._drop_progress_bar is not None:
            manager._drop_progress_bar.set_value(drop.progress)
        if manager._drop_percentage_label is not None:
            manager._drop_percentage_label.set_text(f"{drop.progress:6.1%}")
        # Update the remaining-time labels using the already-running timer state
        _tick_progress(manager)
    except Exception as e:
        print(f"Failed to render drop labels on connect: {e}")


def _build_ws_rows(manager: 'WebUIManager'):
    """(Re)build the websocket status rows inside _ws_container."""
    try:
        if manager._ws_container is None:
            return
        manager._ws_container.clear()
        with manager._ws_container:
            # Always render all MAX_WEBSOCKETS slots, matching gui.py WebsocketStatus._update()
            for idx in range(MAX_WEBSOCKETS):
                entry = manager._ws_data.get(idx)
                ws_name = _('gui', 'websocket', 'websocket').format(id=idx + 1)
                if entry is None:
                    label_text = f"{ws_name}"
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


def _on_channel_switch(manager: 'WebUIManager'):
    """Called when the Switch button is clicked."""
    try:
        from constants import State
        manager._twitch.state_change(State.CHANNEL_SWITCH)()
    except Exception as e:
        print(f"Channel switch error: {e}")


def _on_table_selection(manager: 'WebUIManager', e):
    """Enable/disable the Switch button based on table selection."""
    try:
        has_selection = bool(
            manager._channels_table is not None and manager._channels_table.selected
        )
        if manager._channel_switch_btn is not None:
            if has_selection:
                manager._channel_switch_btn.props(remove='disabled')
            else:
                manager._channel_switch_btn.props('disabled')
    except Exception as ex:
        print(f"Selection handler error: {ex}")


def _on_logout(manager: 'WebUIManager'):
    """Log out by clearing the auth state and cookies, then trigger re-authentication."""
    try:
        from constants import COOKIES_PATH, State
        COOKIES_PATH.unlink(missing_ok=True)
        if manager._twitch._session is not None:
            manager._twitch._session.cookie_jar.clear()
        manager._twitch._auth_state.clear()
        # Clear all UI state immediately so old data doesn't linger while re-authing
        manager.channels.clear()
        manager.inv.clear()
        manager.clear_drop()
        manager._ws_data.clear()
        manager._ws_dirty = True
        manager.login.update(_("gui", "login", "logged_out"), None)
        manager.status.update(_("gui", "status", "idle"))
        # Trigger re-auth the same way as the Settings Reload button
        manager._twitch.state_change(State.INVENTORY_FETCH)()
    except Exception as e:
        print(f"Logout error: {e}")


def _tick_update(manager: 'WebUIManager'):
    """Called every second by ui.timer. Handles dirty flags and countdown."""
    try:
        # WebSocket display
        if manager._ws_dirty:
            manager._ws_dirty = False
            _build_ws_rows(manager)

        # Login display
        if manager._login_dirty:
            manager._login_dirty = False
            if manager._login_status_label is not None:
                manager._login_status_label.set_text(manager._login_status_text)
            if manager._login_button is not None:
                manager._login_button.set_visibility(manager._login_btn_visible)
            if manager._logout_button is not None:
                manager._logout_button.set_visibility(manager._logout_btn_visible)

        # Channel table
        if manager._channels_dirty:
            manager._channels_dirty = False
            _rebuild_channel_table(manager)

        # Progress countdown
        _tick_progress(manager)

    except Exception as e:
        print(f"Tick update error: {e}")


def _tick_progress(manager: 'WebUIManager'):
    """Decrement countdown seconds and update remaining time labels."""
    drop = manager._current_drop
    if drop is None:
        return

    if manager._countdown_active and manager._progress_seconds > 0:
        manager._progress_seconds -= 1

    secs = manager._progress_seconds % 60

    # Drop remaining
    if manager._drop_remaining_label is not None:
        try:
            drop_mins = drop.remaining_minutes
            if manager._progress_seconds < 60 and drop_mins > 0:
                drop_mins -= 1
            h, m = divmod(drop_mins, 60)
            manager._drop_remaining_label.set_text(
                _("gui", "progress", "remaining").format(time=f"{h:>2}:{m:02}:{secs:02}")
            )
        except Exception:
            pass

    # Campaign remaining
    if manager._campaign_remaining_label is not None:
        try:
            camp_mins = drop.campaign.remaining_minutes
            if manager._progress_seconds < 60 and camp_mins > 0:
                camp_mins -= 1
            h, m = divmod(camp_mins, 60)
            manager._campaign_remaining_label.set_text(
                _("gui", "progress", "remaining").format(time=f"{h:>2}:{m:02}:{secs:02}")
            )
        except Exception:
            pass


def _rebuild_channel_table(manager: 'WebUIManager'):
    """Rebuild the channel table rows from manager._channel_map."""
    if manager._channels_table is None:
        return
    rows = []
    for iid, channel in manager._channel_map.items():
        if channel.online:
            status = _("gui", "channels", "online")
        elif channel.pending_online:
            status = _("gui", "channels", "pending")
        else:
            status = _("gui", "channels", "offline")

        # Prefix watching indicator to channel name
        name = channel.name
        if iid == manager._watching_channel_iid:
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
    manager._channels_table.rows = rows
    manager._channels_table.update()


# ---------------------------------------------------------------------------
# Public API called by WebUIManager
# ---------------------------------------------------------------------------

def clear_drop(manager: 'WebUIManager'):
    """Clear the current drop display (mirrors CampaignProgress.display(None))."""
    manager._current_drop = None
    manager._countdown_active = False
    manager._progress_seconds = 0
    try:
        if manager._drop_rewards_label is not None:
            manager._drop_rewards_label.set_text("...")
        if manager._drop_progress_bar is not None:
            manager._drop_progress_bar.set_value(0)
        if manager._drop_percentage_label is not None:
            manager._drop_percentage_label.set_text("-%")
        if manager._drop_remaining_label is not None:
            manager._drop_remaining_label.set_text("")
        if manager._campaign_name_label is not None:
            manager._campaign_name_label.set_text("...")
        if manager._campaign_game_label is not None:
            manager._campaign_game_label.set_text("...")
        if manager._campaign_progress_bar is not None:
            manager._campaign_progress_bar.set_value(0)
        if manager._campaign_percentage_label is not None:
            manager._campaign_percentage_label.set_text("-%")
        if manager._campaign_remaining_label is not None:
            manager._campaign_remaining_label.set_text("")
    except Exception as e:
        print(f"Failed to clear drop display: {e}")


def display_drop(manager: 'WebUIManager', drop, *, countdown: bool = True, subone: bool = False):
    """
    Display current drop/campaign progress.
    Mirrors CampaignProgress.display() exactly.
    """
    if drop is None:
        clear_drop(manager)
        return

    manager._current_drop = drop

    try:
        campaign = drop.campaign

        # --- Campaign section ---
        if manager._campaign_game_label is not None:
            manager._campaign_game_label.set_text(campaign.game.name)
        if manager._campaign_name_label is not None:
            manager._campaign_name_label.set_text(campaign.name)
        if manager._campaign_progress_bar is not None:
            manager._campaign_progress_bar.set_value(campaign.progress)
        if manager._campaign_percentage_label is not None:
            manager._campaign_percentage_label.set_text(
                f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
            )

        # --- Drop section ---
        if manager._drop_rewards_label is not None:
            manager._drop_rewards_label.set_text(drop.rewards_text())
        if manager._drop_progress_bar is not None:
            manager._drop_progress_bar.set_value(drop.progress)
        if manager._drop_percentage_label is not None:
            manager._drop_percentage_label.set_text(f"{drop.progress:6.1%}")

        # --- Timer control ---
        if countdown:
            manager._countdown_active = True
            manager._progress_seconds = 60
        elif subone:
            # show time with 0 seconds (minute will be subtracted on watch)
            manager._countdown_active = False
            manager._progress_seconds = 0
        else:
            # display full time without subtracting
            manager._countdown_active = False
            manager._progress_seconds = 60

        # Immediate time render
        _tick_progress(manager)

    except Exception as e:
        print(f"Failed to update drop display: {e}")
