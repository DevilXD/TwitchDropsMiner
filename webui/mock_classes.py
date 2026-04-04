# Mock classes that provide compatibility with the tkinter GUI interface
# These classes ensure the WebUI can work as a drop-in replacement for GUIManager

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from translate import _

if TYPE_CHECKING:
    from yarl import URL
    from channel import Channel
    from webui.manager import WebUIManager


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class MockTray:
    """Mock system tray - no-op for web UI"""

    def change_icon(self, icon_name: str):
        pass

    def update_title(self, drop):
        pass

    def restore(self):
        pass

    def stop(self):
        pass


class MockStatus:
    """Mirrors StatusBar - updates the status card label"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def update(self, text: str):
        try:
            if self._manager._status_card is not None:
                self._manager._status_card.set_text(text)
            if self._manager._status_label is not None:
                self._manager._status_label.set_text(text)
        except Exception as e:
            print(f"Failed to update status: {e}")

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
        self._manager._countdown_active = False

    def display(self, drop, *, countdown: bool = True, subone: bool = False):
        """Called by twitch.py via GUIManager.display_drop() path"""
        # WebUIManager.display_drop() already calls main_panel.display_drop(),
        # so this is intentionally a no-op to avoid double updates.
        pass

    def minute_almost_done(self) -> bool:
        """True when the countdown timer is at or near 0"""
        return (
            not self._manager._countdown_active
            or self._manager._progress_seconds <= 10
        )


class MockOutput:
    """Mirrors ConsoleOutput"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def print(self, message: str):
        self._manager.print(message)


class MockChannels:
    """
    Mirrors ChannelList - stores channel data on the manager and marks
    _channels_dirty so the ui.timer rebuilds the table.
    """

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    # ------------------------------------------------------------------
    def clear(self):
        self._manager._channel_map.clear()
        self._manager._watching_channel_iid = None
        self._manager._channels_dirty = True

    def set_watching(self, channel: 'Channel'):
        self._manager._watching_channel_iid = channel.iid
        self._manager._channels_dirty = True

    def clear_watching(self):
        self._manager._watching_channel_iid = None
        self._manager._channels_dirty = True

    def get_selection(self) -> 'Channel | None':
        """Return the currently selected Channel (for CHANNEL_SWITCH state)"""
        table = self._manager._channels_table
        if table is None or not table.selected:
            return None
        iid = table.selected[0].get('iid')
        if iid is None:
            return None
        return self._manager._channel_map.get(iid)

    def clear_selection(self):
        table = self._manager._channels_table
        if table is not None:
            table.selected.clear()
            table.update()
        if self._manager._channel_switch_btn is not None:
            self._manager._channel_switch_btn.props('disabled')

    def display(self, channel: 'Channel', *, add: bool = False):
        """Add or update a channel entry in the list"""
        iid = channel.iid
        if add:
            self._manager._channel_map[iid] = channel
        elif iid not in self._manager._channel_map:
            return
        else:
            # Update the stored reference (in case the object changed)
            self._manager._channel_map[iid] = channel
        self._manager._channels_dirty = True

    def remove(self, channel: 'Channel'):
        iid = channel.iid
        self._manager._channel_map.pop(iid, None)
        if self._manager._watching_channel_iid == iid:
            self._manager._watching_channel_iid = None
        self._manager._channels_dirty = True


class MockInventory:
    """Mirrors the inventory display"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def clear(self):
        self._manager._campaigns.clear()
        if self._manager._inventory_container is not None:
            try:
                from webui.components.inventory_panel import refresh_inventory_display
                refresh_inventory_display(self._manager)
            except Exception:
                pass

    async def add_campaign(self, campaign):
        try:
            campaign_data = {
                'name': getattr(campaign, 'name', 'Unknown Campaign'),
                'game': (
                    getattr(campaign.game, 'name', 'Unknown Game')
                    if hasattr(campaign, 'game') else 'Unknown Game'
                ),
                'status': self._get_campaign_status(campaign),
                'progress': getattr(campaign, 'progress', 0),
                'time_remaining': self._get_time_remaining(campaign),
                'campaign_obj': campaign,
            }
            campaign_id = getattr(campaign, 'id', str(len(self._manager._campaigns)))
            self._manager._campaigns[campaign_id] = campaign_data

            if self._manager._inventory_container is not None:
                try:
                    from webui.components.inventory_panel import refresh_inventory_display
                    refresh_inventory_display(self._manager)
                except Exception:
                    pass
        except Exception as e:
            self._manager.print(f"Failed to add campaign: {e}")

    def _get_campaign_status(self, campaign) -> str:
        if getattr(campaign, 'active', False):
            return "Active"
        elif getattr(campaign, 'upcoming', False):
            return "Upcoming"
        elif getattr(campaign, 'expired', False):
            return "Expired"
        return "Unknown"

    def _get_time_remaining(self, campaign) -> str:
        ends_at = getattr(campaign, 'ends_at', None)
        if ends_at is None:
            return ""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            remaining = ends_at - now
            if remaining.total_seconds() > 0:
                days = remaining.days
                hours, rest = divmod(remaining.seconds, 3600)
                minutes, _ = divmod(rest, 60)
                if days > 0:
                    return f"{days}d {hours}h {minutes}m"
                elif hours > 0:
                    return f"{hours}h {minutes}m"
                return f"{minutes}m"
            return "Expired"
        except Exception:
            return ""

    def update_drop(self, drop) -> None:
        """Called when a drop's progress changes - updates inventory display if visible."""
        # Inventory panel updates itself from the campaign/drop objects directly;
        # no extra work needed here.
        pass

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
        await self._manager.coro_unless_closed(self._confirm.wait())

    async def ask_login(self) -> LoginData:
        """Prompt for login via the console; device-code flow is preferred."""
        self.update(_("gui", "login", "required"), None)
        self._manager.grab_attention(sound=False)
        self._manager.print(_("gui", "login", "request"))
        await self.wait_for_login_press()
        return LoginData("", "", "")

    async def ask_enter_code(self, page_url: 'URL', user_code: str) -> None:
        """Show the device activation code and open the browser."""
        self.update(_("gui", "login", "required"), None)
        self._manager.grab_attention(sound=False)
        self._manager.print(_("gui", "login", "request"))
        self._manager.print(
            f"Enter this code on Twitch's device activation page: {user_code}"
        )
        twitch_login_url = f"https://www.twitch.tv/activate?device-code={user_code}"
        self._manager.print(f"URL: {twitch_login_url}")
        await asyncio.sleep(4)
        from utils import webopen
        webopen(page_url)

    def update(self, status: str, user_id: int | None):
        """Update the login status display (mirrors LoginForm.update)"""
        user_str = str(user_id) if user_id is not None else "-"
        self._manager._login_status_text = f"{status}\n{user_str}"
        self._manager._login_dirty = True


class MockWebsocketStatus:
    """
    Mirrors WebsocketStatus - stores per-websocket data on the manager
    and marks _ws_dirty so the ui.timer rebuilds the display.
    """

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")
        data = self._manager._ws_data
        if idx not in data:
            data[idx] = {
                'status': _("gui", "websocket", "disconnected"),
                'topics': 0,
            }
        if status is not None:
            data[idx]['status'] = status
        if topics is not None:
            data[idx]['topics'] = topics
        self._manager._ws_dirty = True

    def remove(self, idx: int):
        self._manager._ws_data.pop(idx, None)
        self._manager._ws_dirty = True


class MockSettings:
    """Mock settings panel"""

    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager
        self._priority_list = _MockList()
        self._exclude_list = _MockList()

    def clear_selection(self):
        pass

    def set_games(self, games):
        pass


class _MockList:
    def configure_theme(self, **kwargs):
        pass


class MockTabs:
    """Mock tabs handler"""

    def current_tab(self) -> int:
        return 0

    def add_view_event(self, callback):
        pass
