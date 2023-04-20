from __future__ import annotations

import sys
import curses
import asyncio
import logging
import traceback
from collections import abc
from datetime import datetime
from typing import Any, TYPE_CHECKING

from translate import _
from base_ui import BaseInterfaceManager, BaseSettingsPanel, BaseInventoryOverview, BaseCampaignProgress, \
    BaseConsoleOutput, BaseChannelList, BaseTrayIcon, BaseLoginForm, BaseWebsocketStatus, BaseStatusBar
from exceptions import ExitRequest
from utils import Game, _T
from constants import (
    OUTPUT_FORMATTER
)

if TYPE_CHECKING:
    from twitch import Twitch
    from channel import Channel
    from inventory import DropsCampaign, TimedDrop

WINDOW_WIDTH = 80
WINDOW_HEIGHT = 9


class _LoggingHandler(logging.Handler):
    def __init__(self, output: CLIManager):
        super().__init__()
        self._output = output

    def emit(self, record):
        self._output.print(self.format(record))


class StatusBar(BaseStatusBar):
    def __init__(self):
        self._window = curses.newwin(1, WINDOW_WIDTH, 1, 0)
        self.update("")

    def update(self, status: str):
        self._window.clear()
        self._window.addstr(0, 0, f"{_('gui', 'status', 'name')}: ", curses.A_BOLD)
        self._window.addstr(status)
        self._window.refresh()

    def clear(self):
        self.update("")


class WebsocketStatus(BaseWebsocketStatus):
    """
    The websocket status display is not implemented in CLI
    """

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        pass

    def remove(self, idx: int):
        pass


class LoginHandler(BaseLoginForm):
    def __init__(self, manager: CLIManager):
        self._manager = manager
        self._window = curses.newwin(1, WINDOW_WIDTH, 0, 0)
        labels = _("gui", "login", "labels").split("\n")
        self._label_status = labels[0] + ' '
        self._label_user_id = labels[1] + ' '

        self.update(_("gui", "login", "logged_out"), None)

    def clear(self, login, password, token):
        pass

    def wait_for_login_press(self):
        pass

    def ask_login(self):
        pass

    async def ask_enter_code(self, user_code: str) -> None:
        self.update(_("gui", "login", "required"), None)
        self._manager.print(_("gui", "login", "request"))

        self._manager.print(f"Open this link to login: https://www.twitch.tv/activate")
        self._manager.print(f"Enter this code on the Twitch's device activation page: {user_code}")

    def update(self, status: str, user_id: int | None):
        self._window.clear()
        self._window.addstr(0, 0, self._label_status, curses.A_BOLD)
        self._window.addstr(status)
        self._window.addstr(0, 30, self._label_user_id, curses.A_BOLD)
        self._window.addstr(str(user_id) if user_id else "-")
        self._window.refresh()


class TrayHandler(BaseTrayIcon):
    """
    Not implemented because not required in CLI
    """

    def is_tray(self) -> bool:
        pass

    def get_title(self, drop: TimedDrop | None) -> str:
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def quit(self):
        pass

    def minimize(self):
        pass

    def restore(self):
        pass

    def notify(
            self, message: str, title: str | None = None, duration: float = 10
    ) -> asyncio.Task[None] | None:
        pass

    def update_title(self, drop: TimedDrop | None):
        pass


class InventoryHandler(BaseInventoryOverview):
    """
    The inventory display is not implemented in CLI
    """

    def refresh(self):
        pass

    async def add_campaign(self, campaign: DropsCampaign) -> None:
        pass

    def clear(self) -> None:
        pass

    @staticmethod
    def get_status(campaign: DropsCampaign) -> tuple[str, str]:
        if campaign.active:
            status_text = _("gui", "inventory", "status", "active")
            status_color = "green"
        elif campaign.upcoming:
            status_text = _("gui", "inventory", "status", "upcoming")
            status_color = "goldenrod"
        else:
            status_text = _("gui", "inventory", "status", "expired")
            status_color = "red"
        return status_text, status_color

    @staticmethod
    def get_progress(drop: TimedDrop) -> tuple[str, str]:
        progress_color = ""
        if drop.is_claimed:
            progress_color = "green"
            progress_text = _("gui", "inventory", "status", "claimed")
        elif drop.can_claim:
            progress_color = "goldenrod"
            progress_text = _("gui", "inventory", "status", "ready_to_claim")
        elif drop.current_minutes or drop.can_earn():
            progress_text = _("gui", "inventory", "percent_progress").format(
                percent=f"{drop.progress:3.1%}",
                minutes=drop.required_minutes,
            )
        else:
            progress_text = _("gui", "inventory", "minutes_progress").format(
                minutes=drop.required_minutes
            )
        return progress_text, progress_color

    def update_drop(self, drop: TimedDrop) -> None:
        pass


class SettingsHandler(BaseSettingsPanel):
    """
    The setting panel is not implemented in CLI
    Please edit settings.json manually
    """

    def clear_selection(self):
        pass

    def update_notifications(self):
        pass

    def update_autostart(self):
        pass

    def set_games(self, games: abc.Iterable[Game]) -> None:
        pass

    def priorities(self) -> dict[str, int]:
        return {}

    def priority_add(self):
        pass

    def priority_move(self, up):
        pass

    def priority_delete(self):
        pass

    def priority_only(self):
        pass

    def exclude_add(self):
        pass

    def exclude_delete(self):
        pass


class ProgressHandler(BaseCampaignProgress):
    def __init__(self):
        self._window = curses.newwin(WINDOW_HEIGHT, WINDOW_WIDTH, 3, 0)

        self._drop: TimedDrop | None = None
        self._timer_task: asyncio.Task[None] | None = None

        self._campaign_name: str = ""
        self._campaign_game: str = ""
        self._campaign_progress: float = 0
        self._campaign_percentage: str = ""
        self._campaign_remaining: str = ""

        self._drop_rewards: str = ""
        self._drop_progress: float = 0
        self._drop_percentage: str = ""
        self._drop_remaining: str = ""

        self.display(None)

    @staticmethod
    def _divmod(minutes: int, seconds: int) -> tuple[int, int]:
        if seconds < 60 and minutes > 0:
            minutes -= 1
        hours, minutes = divmod(minutes, 60)
        return hours, minutes

    def _update_time(self, seconds: int):
        drop = self._drop
        if drop is not None:
            drop_minutes = drop.remaining_minutes
            campaign_minutes = drop.campaign.remaining_minutes
        else:
            drop_minutes = 0
            campaign_minutes = 0

        dseconds = seconds % 60
        hours, minutes = self._divmod(drop_minutes, seconds)
        self._drop_remaining = f"{hours:>2}:{minutes:02}:{dseconds:02}"

        hours, minutes = self._divmod(campaign_minutes, seconds)
        self._campaign_remaining = f"{hours:>2}:{minutes:02}:{dseconds:02}"

    async def _timer_loop(self):
        seconds = 60
        self._update_time(seconds)
        while seconds > 0:
            await asyncio.sleep(1)
            seconds -= 1
            self._update_time(seconds)
        self._timer_task = None

    def start_timer(self):
        if self._timer_task is None:
            if self._drop is None or self._drop.remaining_minutes <= 0:
                # if we're starting the timer at 0 drop minutes,
                # all we need is a single instant time update setting seconds to 60,
                # to avoid substracting a minute from campaign minutes
                self._update_time(60)
            else:
                self._timer_task = asyncio.create_task(self._timer_loop())

    def stop_timer(self):
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    def display(self, drop: TimedDrop | None, *, countdown: bool = True, subone: bool = False):
        self._drop = drop
        self.stop_timer()

        if drop is None:
            # clear the drop display
            self._drop_rewards = "..."
            self._drop_progress = 0
            self._drop_percentage = "-%"
            self._campaign_name = "..."
            self._campaign_game = "..."
            self._campaign_progress = 0
            self._campaign_percentage = "-%"
            self._update_time(0)
            self._update()
            return

        self._drop_rewards = drop.rewards_text()
        self._drop_progress = drop.progress
        self._drop_percentage = f"{drop.progress:6.1%}"

        campaign = drop.campaign
        self._campaign_name = campaign.name
        self._campaign_game = campaign.game.name
        self._campaign_progress = campaign.progress
        self._campaign_percentage = f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"

        if countdown:
            # restart our seconds update timer
            self.start_timer()
        elif subone:
            # display the current remaining time at 0 seconds (after substracting the minute)
            # this is because the watch loop will substract this minute
            # right after the first watch payload returns with a time update
            self._update_time(0)
        else:
            # display full time with no substracting
            self._update_time(60)

        self._update()

    @staticmethod
    def _progress_bar(progress: float, width: int) -> str:
        finished = int((width - 2) * progress)
        remaining = int((width - 2) - finished)
        return f"[{'=' * finished}{'-' * remaining}]"

    def _update(self):
        self._window.clear()

        self._window.addstr(0, 0, _("gui", "progress", "game") + ' ', curses.A_BOLD)
        self._window.addstr(self._campaign_game)
        self._window.addstr(1, 0, _("gui", "progress", "campaign") + ' ', curses.A_BOLD)
        self._window.addstr(self._campaign_name)
        self._window.addstr(2, 0, _("gui", "progress", "campaign_progress") + ' ', curses.A_BOLD)
        self._window.addstr(f"{self._campaign_percentage}")
        self._window.addstr(2, 30, _("gui", "progress", "remaining").format(time=self._campaign_remaining))
        self._window.addstr(3, 0, self._progress_bar(self._campaign_progress, WINDOW_WIDTH))

        self._window.addstr(5, 0, _("gui", "progress", "drop") + ' ', curses.A_BOLD)
        self._window.addstr(self._drop_rewards)
        self._window.addstr(6, 0, _("gui", "progress", "drop_progress") + ' ', curses.A_BOLD)
        self._window.addstr(f"{self._drop_percentage}")
        self._window.addstr(6, 30, _("gui", "progress", "remaining").format(time=self._drop_remaining))
        self._window.addstr(7, 0, self._progress_bar(self._drop_progress, WINDOW_WIDTH))

        self._window.refresh()


class ConsoleOutput(BaseConsoleOutput):
    _BUFFER_SIZE = 6

    def __init__(self):
        self._window = curses.newwin(self._BUFFER_SIZE, WINDOW_WIDTH, 12, 0)

        self._buffer: list[str] = []

    def print(self, message: str):
        stamp = datetime.now().strftime("%X") + ": "
        max_length = WINDOW_WIDTH - len(stamp)

        lines = message.split("\n")  # Split the message by lines
        for line in lines:
            for i in range(0, len(line), max_length):  # Split te line by length
                self._buffer.append(stamp + line[i:i + max_length])

        self._buffer = self._buffer[-self._BUFFER_SIZE:]  # Keep the last lines
        self._update()

    def _update(self):
        self._window.clear()
        for i, line in enumerate(self._buffer):
            self._window.addstr(i, 0, line)
        self._window.refresh()


class ChannelsHandler(BaseChannelList):
    """
    The channel list is not implemented in CLI
    """

    def shrink(self):
        pass

    def clear(self):
        pass

    def set_watching(self, channel: Channel):
        pass

    def clear_watching(self):
        pass

    def get_selection(self) -> Channel | None:
        pass

    def clear_selection(self):
        pass

    def display(self, channel: Channel, *, add: bool = False):
        pass

    def remove(self, channel: Channel):
        pass


class CLIManager(BaseInterfaceManager):
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._close_requested = asyncio.Event()

        # GUI
        self._stdscr = curses.initscr()

        try:
            self.tray = TrayHandler()
            self.status = StatusBar()
            self.websockets = WebsocketStatus()
            self.inv = InventoryHandler()
            self.login = LoginHandler(self)
            self.progress = ProgressHandler()
            self.output = ConsoleOutput()
            self.channels = ChannelsHandler()
            self.settings = SettingsHandler()
        except curses.error:
            curses.nocbreak()
            self._stdscr.keypad(False)
            curses.echo()
            curses.endwin()

            sys.stderr.write(
                f"An error occurred while creating the curses window, probably due to the window size being too "
                f"small (minimum width = {WINDOW_WIDTH}, minimum height = {WINDOW_HEIGHT}).\n"
            )
            sys.stderr.write(traceback.format_exc())
            sys.exit(1)

        # register logging handler
        self._handler = _LoggingHandler(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logger = logging.getLogger("TwitchDrops")
        logger.addHandler(self._handler)
        if (logging_level := logger.getEffectiveLevel()) < logging.ERROR:
            self.print(f"Logging level: {logging.getLevelName(logging_level)}")

    def wnd_proc(self, hwnd, msg, w_param, l_param):
        pass

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    async def wait_until_closed(self):
        # wait until the user closes the window
        await self._close_requested.wait()

    async def coro_unless_closed(self, coro: abc.Awaitable[_T]) -> _T:
        # In Python 3.11, we need to explicitly wrap awaitables
        tasks = [asyncio.ensure_future(coro), asyncio.ensure_future(self._close_requested.wait())]
        done: set[asyncio.Task[Any]]
        pending: set[asyncio.Task[Any]]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if self._close_requested.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def prevent_close(self):
        self._close_requested.clear()

    def start(self):
        curses.noecho()
        curses.cbreak()
        self._stdscr.keypad(True)

        # self.progress.start_timer()

    def stop(self):
        curses.nocbreak()
        self._stdscr.keypad(False)
        curses.echo()
        curses.endwin()

        self.progress.stop_timer()

    def close(self, *args) -> int:
        self._close_requested.set()
        # notify client we're supposed to close
        self._twitch.close()
        return 0

    def close_window(self):
        """
        Closes the window. Invalidates the logger.
        """
        logging.getLogger("TwitchDrops").removeHandler(self._handler)

    def unfocus(self, event):
        pass

    def save(self, *, force: bool = False):
        pass

    def set_games(self, games: abc.Iterable[Game]):
        self.settings.set_games(games)

    def display_drop(self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)

    def clear_drop(self):
        self.progress.display(None)

    def print(self, message: str):
        self.output.print(message)
