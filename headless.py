from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from twitch import Twitch
    from inventory import TimedDrop, DropsCampaign
    from utils import Game
    from gui import LoginData

class MockLogin:
    def ask_login(self) -> LoginData:
        raise NotImplementedError("Login is not supported in headless mode")

    def ask_enter_code(self, page_url, user_code):
        print(f"Please go to {page_url} and enter the code: {user_code}")

    def update(self, status: str, user_id: int | None):
        print(f"Login status: {status}, user_id: {user_id}")

class MockTray:
    def change_icon(self, state: str):
        pass

class MockStatus:
    def update(self, text: str):
        logger.info(f"Status: {text}")

class MockChannels:
    def __init__(self):
        self.channels = {}

    def get_selection(self):
        return None

    def set_watching(self, channel):
        logger.info(f"Watching channel: {channel.name}")

    def clear_watching(self):
        logger.info("Stopped watching channel")

    def display(self, channel, *, add: bool = False):
        if add:
            self.channels[channel.id] = channel
            logger.info(f"Added channel: {channel.name}")
        else:
            logger.info(f"Updated channel: {channel.name}")

    def clear(self):
        self.channels.clear()
        logger.info("Cleared all channels")

class MockProgress:
    def is_counting(self) -> bool:
        return False

    def stop_timer(self):
        pass

    def display(self, drop: TimedDrop | None, *, countdown: bool = True, subone: bool = False):
        pass


class MockInventory:
    async def add_campaign(self, campaign: DropsCampaign) -> None:
        pass

    def clear(self) -> None:
        pass


logger = logging.getLogger("TwitchDrops")


class HeadlessGUIManager:
    def __init__(self, twitch: "Twitch"):
        self._twitch = twitch
        self._close_requested = asyncio.Event()
        self.login = MockLogin()
        self.tray = MockTray()
        self.status = MockStatus()
        self.channels = MockChannels()
        self.progress = MockProgress()
        self.inv = MockInventory()

    def print(self, message: str):
        print(message)

    def start(self):
        pass

    def stop(self):
        pass

    def close_window(self):
        pass

    @property
def close_requested(self) -> bool:
        return self._close_requested.is_set()

    def prevent_close(self):
        self._close_requested.clear()

    async def wait_until_closed(self):
        await self._close_requested.wait()

    def close(self, *args: Any):
        self._close_requested.set()
        self._twitch.close()
        return 0

    def display_drop(self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False):
        if drop:
            logger.info(f"Current drop: {drop.rewards_text()} for {drop.campaign.game.name} - {drop.progress:.2%}")
        else:
            logger.info("No active drop")

    def clear_drop(self):
        logger.info("No longer tracking any drop")

    def set_games(self, games: set[Game]) -> None:
        if games:
            logger.info(f"Targeting the following games: {', '.join(game.name for game in games)}")
        else:
            logger.info("No games are being targeted for drops")

    def grab_attention(self, *, sound: bool = True):
        pass

    def save(self, *, force: bool = False) -> None:
        pass
