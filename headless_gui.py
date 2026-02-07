from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from channel import Channel
    from inventory import DropsCampaign, TimedDrop
    from utils import Game


# Headless GUI implementation for web mode
# These classes CAPTURE real data from twitch.py so the web API can read it
# instead of reaching into twitch internals.


class DummyProgress:
    """Captures current drop progress for the web API."""

    def __init__(self):
        self._drop: TimedDrop | None = None
        self._countdown: bool = True
        self._subone: bool = False
        self._lock = threading.Lock()

    @property
    def current_drop(self) -> TimedDrop | None:
        with self._lock:
            return self._drop

    def minute_almost_done(self) -> bool:
        # In headless mode, always return False to continue normal processing
        return False

    def stop_timer(self):
        pass

    def start_timer(self):
        pass

    def display(self, drop=None, *, countdown: bool = True, subone: bool = False):
        with self._lock:
            self._drop = drop
            self._countdown = countdown
            self._subone = subone


class DummyChannels:
    """Captures channel data for the web API."""

    def __init__(self):
        self._channels: dict[int, Channel] = {}
        self._watching: Channel | None = None
        self._lock = threading.Lock()

    @property
    def watching(self) -> Channel | None:
        with self._lock:
            return self._watching

    @property
    def all_channels(self) -> list[Channel]:
        with self._lock:
            return list(self._channels.values())

    def clear(self):
        with self._lock:
            self._channels.clear()
            self._watching = None

    def set_watching(self, channel):
        with self._lock:
            self._watching = channel

    def clear_watching(self):
        with self._lock:
            self._watching = None

    def get_selection(self):
        return None

    def display(self, channel, *, add: bool = False):
        with self._lock:
            self._channels[channel.iid] = channel

    def remove(self, channel):
        with self._lock:
            self._channels.pop(channel.iid, None)
            if self._watching is not None and self._watching.iid == channel.iid:
                self._watching = None

    def shrink(self):
        pass


class DummyWebsocketStatus:
    """Captures websocket connection status for the web API."""

    def __init__(self):
        self._websockets: dict[int, dict] = {}
        self._lock = threading.Lock()

    @property
    def statuses(self) -> dict[int, dict]:
        with self._lock:
            return dict(self._websockets)

    def update(self, idx, *, status=None, topics=None):
        with self._lock:
            if idx not in self._websockets:
                self._websockets[idx] = {'status': None, 'topics': 0}
            if status is not None:
                self._websockets[idx]['status'] = status
            if topics is not None:
                self._websockets[idx]['topics'] = topics

    def remove(self, idx):
        with self._lock:
            self._websockets.pop(idx, None)


class DummyInventoryOverview:
    """Captures inventory/campaign data for the web API."""

    def __init__(self):
        self._campaigns: dict[str, DropsCampaign] = {}
        self._lock = threading.Lock()

    @property
    def campaigns(self) -> list[DropsCampaign]:
        with self._lock:
            return list(self._campaigns.values())

    def clear(self):
        with self._lock:
            self._campaigns.clear()

    def add_campaign(self, campaign):
        """Store campaign data. Returns an awaitable no-op for async callers."""
        with self._lock:
            self._campaigns[campaign.id] = campaign

        import asyncio
        async def _noop():
            pass
        return _noop()

    def update_drop(self, drop):
        pass  # Drop data is updated in-place on the objects already stored


class DummyGUI:
    """Data-capturing GUI stub for headless/web mode.

    Instead of discarding data like no-op stubs, these objects store
    the latest state so the Flask web API can read it directly.
    """

    def __init__(self, client=None):
        self.client = client
        self.close_requested = False
        self.status = DummyStatus()
        self.tray = DummyTray()
        self.progress = DummyProgress()
        self.channels = DummyChannels()
        self.inv = DummyInventoryOverview()
        self.websockets = DummyWebsocketStatus()
        self._games: set[Game] = set()
        self._log_messages: list[tuple[str, str]] = []  # (timestamp, message)
        self._log_lock = threading.Lock()
        self._max_log_lines = 500

    def start(self):
        pass

    def close(self):
        self.close_requested = True

    def grab_attention(self, sound=False):
        pass

    async def wait_until_closed(self):
        return

    async def coro_unless_closed(self, coro):
        """Await a coroutine unless close has been requested."""
        return await coro

    def stop(self):
        pass

    def close_window(self):
        pass

    def set_games(self, games):
        self._games = set(games) if games else set()

    def clear_drop(self):
        self.progress.display(None)

    def display_drop(self, drop, *, countdown: bool = True, subone: bool = False):
        self.progress.display(drop, countdown=countdown, subone=subone)

    def print(self, message: str):
        with self._log_lock:
            ts = datetime.now(timezone.utc).isoformat()
            self._log_messages.append((ts, message))
            # Trim old messages
            if len(self._log_messages) > self._max_log_lines:
                self._log_messages = self._log_messages[-self._max_log_lines:]

    def get_log(self, last_n: int = 100) -> list[tuple[str, str]]:
        """Return the last N log messages as (timestamp, message) tuples."""
        with self._log_lock:
            return list(self._log_messages[-last_n:])

    def save(self, *, force: bool = False):
        pass

    def prevent_close(self):
        pass


class DummyStatus:
    """Captures status text for the web API."""

    def __init__(self):
        self._message: str = ''
        self._lock = threading.Lock()

    @property
    def message(self) -> str:
        with self._lock:
            return self._message

    def update(self, message):
        with self._lock:
            self._message = str(message) if message else ''

    def clear(self):
        with self._lock:
            self._message = ''


class DummyTray:
    """Captures tray state for the web API."""

    def __init__(self):
        self._icon_state: str = 'idle'
        self._notifications: list[tuple[str, str, str]] = []  # (timestamp, title, message)
        self._lock = threading.Lock()
        self._max_notifications = 50

    @property
    def icon_state(self) -> str:
        with self._lock:
            return self._icon_state

    @property
    def notifications(self) -> list[tuple[str, str, str]]:
        with self._lock:
            return list(self._notifications)

    def change_icon(self, icon_name):
        with self._lock:
            self._icon_state = icon_name

    def notify(self, message, title=""):
        with self._lock:
            ts = datetime.now(timezone.utc).isoformat()
            self._notifications.append((ts, title, message))
            if len(self._notifications) > self._max_notifications:
                self._notifications = self._notifications[-self._max_notifications:]


# For monkey patching the regular GUI import
class GUIManager(DummyGUI):
    """A placeholder for the GUI manager in web mode."""

    def __init__(self, client):
        super().__init__(client)


# Dummy classes for other GUI components that might be imported
class LoginForm:
    pass

class WebsocketStatus:
    pass

class InventoryOverview:
    pass

class ChannelList:
    pass


def apply_headless_patches():
    """Apply patches to make the application work in headless/web mode."""
    # Monkey patch the GUI class
    sys.modules['gui'] = sys.modules[__name__]