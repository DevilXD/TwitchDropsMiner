# Adapter classes that make WebUIManager look like the tkinter GUIManager.
#
# Background
# ----------
# twitch.py calls methods on a set of widget-like objects attached to the GUI
# manager (manager.status, manager.channels, manager.login, …).  Those objects
# were originally tkinter widgets.  The classes in this module are lightweight
# adapters that implement the same method signatures so that twitch.py requires
# no changes when the web UI is in use.
#
# How each class works
# --------------------
#
# The plain Python state lives on MainPanel (not WebUIManager) and persists so
# that late-joining clients can restore the full current view on page load
# without waiting for the next update.
#
# Correspondence to tkinter classes
# ----------------------------------
#   MockTray            → system tray icon         (no-op; no tray in browser)
#   MockStatus          → StatusBar                (header label + status card)
#   MockProgress        → CampaignProgress         (delegates to display_drop)
#   MockOutput          → ConsoleOutput            (forwards to manager.print)
#   MockChannels        → ChannelList              (manages _channel_map)
#   MockInventory       → InventoryOverview        (manages _inventory_campaigns)
#   MockLoginForm       → LoginForm                (device-code / password flow)
#   MockWebsocketStatus → WebsocketStatus          (manages _ws_data)
#   MockSettings        → settings panel widget    (no-op stubs)
#   MockTabs            → tab controller           (no-op stubs)

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from translate import _

if TYPE_CHECKING:
    from yarl import URL
    from channel import Channel
    from webui.manager import WebUIManager
    from utils import Game


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class MockTray:
    """Mock system tray - no-op for web UI"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def change_icon(self, icon_name: str):
        pass

    def update_title(self, drop):
        pass

    def restore(self):
        pass

    def stop(self):
        pass

    def notify(self, message: str, title: str | None = None, duration: float = 10):
        text = f"{title}: {message}" if title else message
        from nicegui import Client, ui
        for client in list(Client.instances.values()):
            with client:
                ui.notify(text, timeout=duration * 1000)


class MockStatus:
    """Mirrors StatusBar - updates the status card label"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def update(self, text: str):
        self._manager._main_panel._status_text = text  # persists for late-joining clients
        self._manager._main_panel.flush_status(text)

    def clear(self):
        self.update("")


class MockProgress:
    """
    Mirrors CampaignProgress - delegates display() to the main_panel
    display_drop() function via WebUIManager.display_drop().
    """

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def stop_timer(self):
        self._manager._main_panel._countdown_active = False

    def display(self, drop, *, countdown: bool = True, subone: bool = False):
        """Called by twitch.py via GUIManager.display_drop() path"""
        # WebUIManager.display_drop() already calls main_panel.display_drop(),
        # so this is intentionally a no-op to avoid double updates.
        pass

    def minute_almost_done(self) -> bool:
        """True when the countdown timer is at or near 0"""
        panel = self._manager._main_panel
        return not panel._countdown_active or panel._progress_seconds <= 10


class MockOutput:
    """Mirrors ConsoleOutput"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def print(self, message: str):
        self._manager.print(message)


class MockChannels:
    """
    Mirrors ChannelList - stores channel data on the manager and schedules
    a channel table rebuild on the NiceGUI event loop.
    """

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def clear(self):
        panel = self._manager._main_panel
        panel._channel_map.clear()
        panel._watching_channel_iid = None
        panel.rebuild_channel_table()

    def set_watching(self, channel: 'Channel'):
        panel = self._manager._main_panel
        panel._watching_channel_iid = channel.iid
        panel.rebuild_channel_table()

    def clear_watching(self):
        panel = self._manager._main_panel
        panel._watching_channel_iid = None
        panel.rebuild_channel_table()

    def get_selection(self) -> 'Channel | None':
        """Return the currently selected Channel (for CHANNEL_SWITCH state)"""
        panel = self._manager._main_panel
        iid = panel._selected_channel_iid
        if iid is None:
            return None
        return panel._channel_map.get(iid)

    def clear_selection(self):
        panel = self._manager._main_panel
        panel._selected_channel_iid = None
        panel.clear_selection()

    def display(self, channel: 'Channel', *, add: bool = False):
        """Add or update a channel entry in the list"""
        panel = self._manager._main_panel
        iid = channel.iid
        if add:
            panel._channel_map[iid] = channel
        elif iid not in panel._channel_map:
            return
        else:
            panel._channel_map[iid] = channel
        panel.rebuild_channel_table()

    def remove(self, channel: 'Channel'):
        panel = self._manager._main_panel
        iid = channel.iid
        panel._channel_map.pop(iid, None)
        if panel._watching_channel_iid == iid:
            panel._watching_channel_iid = None
        panel.rebuild_channel_table()


class MockInventory:
    """
    Mirrors InventoryOverview - stores DropsCampaign objects and schedules
    inventory panel rebuilds on the NiceGUI event loop.
    """

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def clear(self):
        self._manager._inventory_panel.clear()

    async def add_campaign(self, campaign) -> None:
        """Delegates to InventoryPanel.add_campaign."""
        self._manager._inventory_panel.add_campaign(campaign)

    def update_drop(self, drop) -> None:
        """Mirrors InventoryOverview.update_drop() - delegates to InventoryPanel."""
        self._manager._inventory_panel.update_drop(drop)

    def configure_theme(self, *, bg: str):
        pass


class MockLoginForm:
    """
    Mirrors LoginForm - updates the login status labels and handles
    the device-code activation flow.
    """

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager
        self._confirm = asyncio.Event()

    def clear(self, login: bool = False, password: bool = False, token: bool = False):
        pass

    async def wait_for_login_press(self) -> None:
        self._confirm.clear()
        self._manager._main_panel._login_btn_visible = True
        self._manager._main_panel.flush_login()
        await self._manager.coro_unless_closed(self._confirm.wait())

    async def ask_login(self) -> LoginData:
        """Prompt for login via the console; device-code flow is preferred."""
        self.update(_("gui", "login", "required"), None)
        self._manager.grab_attention(sound=False)
        self._manager.print(_("gui", "login", "request"))
        await self.wait_for_login_press()
        return LoginData("", "", "")

    async def ask_enter_code(self, page_url: 'URL', user_code: str) -> None:
        """Show the device activation code and wait for login button before opening browser."""
        self.update(_("gui", "login", "required"), None)
        self._manager.grab_attention(sound=False)
        self._manager.print(_("gui", "login", "request"))
        self._manager.print(
            f"Enter this code on Twitch's device activation page: {user_code}"
        )
        twitch_login_url = f"https://www.twitch.tv/activate?device-code={user_code}"
        self._manager.print(f"URL: {twitch_login_url}")
        await self.wait_for_login_press()
        from utils import webopen
        webopen(page_url)

    def update(self, status: str, user_id: int | None):
        panel = self._manager._main_panel
        user_str = str(user_id) if user_id is not None else "-"
        panel._login_status_text = f"{status}\n{user_str}"
        panel._logout_btn_visible = (status == _("gui", "login", "logged_in"))
        if status != _("gui", "login", "required"):
            panel._login_btn_visible = False
        panel.flush_login()
        # Mirror login state to the status bar when the main loop hasn't set it yet
        login_statuses = (
            _("gui", "login", "logging_in"),
            _("gui", "login", "required"),
            _("gui", "login", "logged_out"),
        )
        if status in login_statuses:
            self._manager.status.update(status)


class MockWebsocketStatus:
    """
    Mirrors WebsocketStatus - stores per-websocket data on the manager
    and schedules a UI rebuild on the NiceGUI event loop.
    """

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")
        data = self._manager._main_panel._ws_data
        if idx not in data:
            data[idx] = {
                'status': _("gui", "websocket", "disconnected"),
                'topics': 0,
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
                        data[idx]['status'] = live_status
                except Exception:
                    pass
        if status is not None:
            data[idx]['status'] = status
        if topics is not None:
            data[idx]['topics'] = topics
        self._manager.rebuild_ws()

    def remove(self, idx: int):
        self._manager._main_panel._ws_data.pop(idx, None)
        self._manager.rebuild_ws()


class MockSettings:
    """
    Mirrors the tkinter settings panel widget.

    twitch.py calls clear_selection() and set_games() on the settings object;
    those operations are handled directly by the NiceGUI settings panel in
    webui/components/settings_panel.py, so these stubs are intentional no-ops.
    _priority_list / _exclude_list are kept so that any attribute access that
    expects a list-like widget (e.g. configure_theme) does not raise.
    """

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager
        self._priority_list = _MockList()
        self._exclude_list = _MockList()

    def clear_selection(self):
        pass

    def set_games(self, games: set[Game]):
        pass


class _MockList:
    """Stub for tkinter Listbox-like objects that only need configure_theme."""
    def configure_theme(self, **kwargs):
        pass


class MockTabs:
    """
    Mirrors the tkinter tab controller.

    twitch.py uses current_tab() to read the active tab index and
    add_view_event() to register a callback when the tab changes.  Neither is
    meaningful for the web UI (tab state lives in the browser), so both are
    stubs.  current_tab() returns 0 (the Main tab) as a safe default.
    """

    def current_tab(self) -> int:
        return 0

    def add_view_event(self, callback):
        pass
