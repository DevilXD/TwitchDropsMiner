from __future__ import annotations

import curses
import asyncio
import logging
from collections import abc
from math import log10, ceil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

from translate import _
from exceptions import ExitRequest
from utils import Game, _T
from constants import (
    OUTPUT_FORMATTER, WS_TOPICS_LIMIT
)

if TYPE_CHECKING:
    from twitch import Twitch
    from channel import Channel
    from settings import Settings
    from inventory import DropsCampaign, TimedDrop

DIGITS = ceil(log10(WS_TOPICS_LIMIT))

WINDOW_WIDTH = 100


class _LoggingHandler(logging.Handler):
    def __init__(self, output: CLIManager):
        super().__init__()
        self._output = output

    def emit(self, record):
        self._output.print(self.format(record))


class StatusBar:
    def __init__(self):
        self._window = curses.newwin(1, WINDOW_WIDTH, 1, 0)
        self.update("")

    def update(self, status: str):
        self._window.clear()
        self._window.addstr(0, 0, f"{_('gui', 'status', 'name')}: ")
        self._window.addstr(status)
        self._window.refresh()


@dataclass
class _WSEntry:
    status: str
    topics: int


class WebsocketStatus:
    """
    The websocket status display is removed from CLI mode
    to reduce unnecessary display space use
    """

    def __init__(self):
        # self._window = curses.newwin(MAX_WEBSOCKETS, 30, 1, 0)
        # self._label = '\n'.join(
        #     _("gui", "websocket", "websocket").format(id=i)
        #     for i in range(1, MAX_WEBSOCKETS + 1)
        # )
        #
        # self._status: str = ""
        # self._topics: str = ""
        #
        # self._items: dict[int, _WSEntry | None] = {i: None for i in range(MAX_WEBSOCKETS)}
        # self._update()
        pass

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        # if status is None and topics is None:
        #     raise TypeError("You need to provide at least one of: status, topics")
        # entry = self._items.get(idx)
        # if entry is None:
        #     entry = self._items[idx] = _WSEntry(
        #         status=_("gui", "websocket", "disconnected"), topics=0
        #     )
        # if status is not None:
        #     entry.status = status
        # if topics is not None:
        #     entry.topics = topics
        # self._update()
        pass

    def remove(self, idx: int):
        # if idx in self._items:
        #     del self._items[idx]
        #     self._update()
        pass

    # def _update(self):
    #     self._window.clear()
    #     self._window.addstr(0, 0, self._label)
    #
    #     for idx in range(MAX_WEBSOCKETS):
    #         if (item := self._items.get(idx)) is not None:
    #             self._window.addstr(idx, 15, item.status)
    #             self._window.addstr(idx, 25, f"{item.topics:>{DIGITS}}/{WS_TOPICS_LIMIT}")
    #
    #     self._window.refresh()


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class LoginHandler:
    def __init__(self, manager: CLIManager):
        self._manager = manager
        self._window = curses.newwin(1, WINDOW_WIDTH, 0, 0)
        labels = _("gui", "login", "labels").split("\n")
        self._label_status = labels[0] + ' '
        self._label_user_id = labels[1] + ' '

        self.update(_("gui", "login", "logged_out"), None)

    async def ask_enter_code(self, user_code: str) -> None:
        self.update(_("gui", "login", "required"), None)
        self._manager.print(_("gui", "login", "request"))

        self._manager.print(f"Open this link to login: https://www.twitch.tv/activate")
        self._manager.print(f"Enter this code on the Twitch's device activation page: {user_code}")

    def update(self, status: str, user_id: int | None):
        self._window.clear()
        self._window.addstr(0, 0, self._label_status)
        self._window.addstr(status)
        self._window.addstr(0, 30, self._label_user_id)
        self._window.addstr(str(user_id) if user_id else "-")
        self._window.refresh()


@dataclass
class CampaignDisplay:
    name: str
    status: str = ""
    starts_at: str = ""
    ends_at: str = ""
    link: str = ""
    allowed_channels: str = ""
    drops: list[str] = field(default_factory=list)
    visible: bool = True


class DropDisplay:
    benefits: list[str] = []
    progress: str = ""


class InventoryHandler:
    """
    The inventory display is removed from CLI mode
    to reduce unnecessary display space use
    """

    def __init__(self, manager: CLIManager):
        # self._settings: Settings = manager._twitch.settings
        # self._filters: dict[str, bool] = {
        #     "linked": True,
        #     "upcoming": True,
        #     "expired": False,
        #     "excluded": False,
        #     "finished": False,
        # }
        # # manager.tabs.add_view_event(self._on_tab_switched)
        #
        # # Inventory view
        # self._campaigns: dict[DropsCampaign, CampaignDisplay] = {}
        # self._drops: dict[str, DropDisplay] = {}
        pass

    def _update_visibility(self, campaign: DropsCampaign):
        # True if the campaign is supposed to show, False makes it hidden.
        # campaign_display = self._campaigns[campaign]
        # linked = self._filters["linked"]
        # expired = self._filters["expired"]
        # excluded = self._filters["excluded"]
        # upcoming = self._filters["upcoming"]
        # finished = self._filters["finished"]
        # priority_only = self._settings.priority_only
        # campaign_display.visible = (
        #         (not linked or campaign.linked)
        #         and (campaign.active or upcoming and campaign.upcoming or expired and campaign.expired)
        #         and (
        #                 excluded
        #                 or (
        #                         campaign.game.name not in self._settings.exclude
        #                         and not priority_only or campaign.game.name in self._settings.priority
        #                 )
        #         )
        #         and (finished or not campaign.finished)
        # )
        pass

    def _on_tab_switched(self) -> None:
        # if self._manager.tabs.current_tab() == 1:
        #     # refresh only if we're switching to the tab
        #     self.refresh()
        pass

    def refresh(self):
        # for campaign in self._campaigns:
        #     # status
        #     status_label = self._campaigns[campaign]["status"]
        #     status_text, status_color = self.get_status(campaign)
        #     status_label.config(text=status_text, foreground=status_color)
        #     # visibility
        #     self._update_visibility(campaign)
        # self._canvas_update()
        pass

    def _canvas_update(self):
        pass

    async def add_campaign(self, campaign: DropsCampaign) -> None:
        # # Name
        # campaign_display = CampaignDisplay(name=campaign.name)
        #
        # # Status
        # status_text, status_color = self.get_status(campaign)
        # campaign_display.status = status_text
        #
        # # Starts / Ends
        # campaign_display.starts_at = _("gui", "inventory", "starts").format(
        #     time=campaign.starts_at.astimezone().replace(microsecond=0, tzinfo=None))
        # campaign_display.ends_at = _("gui", "inventory", "ends").format(
        #     time=campaign.ends_at.astimezone().replace(microsecond=0, tzinfo=None))
        #
        # # Linking status
        # if campaign.linked:
        #     campaign_display.link = _("gui", "inventory", "status", "linked")
        # else:
        #     campaign_display.link = _("gui", "inventory", "status", "not_linked")
        # campaign_display.link += campaign.link_url
        #
        # # ACL channels
        # acl = campaign.allowed_channels
        # if acl:
        #     if len(acl) <= 5:
        #         allowed_text: str = '\n'.join(ch.name for ch in acl)
        #     else:
        #         allowed_text = '\n'.join(ch.name for ch in acl[:4])
        #     allowed_text += (
        #         f"\n{_('gui', 'inventory', 'and_more').format(amount=len(acl) - 4)}"
        #     )
        # else:
        #     allowed_text = _("gui", "inventory", "all_channels")
        # campaign_display.allowed_channels = f"{_('gui', 'inventory', 'allowed_channels')}\n{allowed_text}"
        #
        # # Drops display
        # for i, drop in enumerate(campaign.drops):
        #     campaign_display.drops.append(drop.id)
        #     drop_display = DropDisplay()
        #
        #     # Benefits
        #     for benefit in drop.benefits:
        #         drop_display.benefits.append(benefit.name)
        #
        #     # Progress
        #     progress_text, progress_color = self.get_progress(drop)
        #     drop_display.progress = progress_text
        #
        # self._campaigns[campaign] = campaign_display
        #
        # # if self._manager.tabs.current_tab() == 1:
        # #     self._update_visibility(campaign)
        # #     self._canvas_update()
        pass

    def clear(self) -> None:
        # self._drops.clear()
        # self._campaigns.clear()
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
        # if drop.id not in self._drops:
        #     return
        #
        # progress_text, progress_color = self.get_progress(drop)
        # self._drops[drop.id].progress = progress_text
        pass


class SettingsHandler:
    """
    The setting panel has been removed from CLI mode
    to reduce unnecessary display space use
    Please edit settings.json manually
    """

    def __init__(self, manager: CLIManager):
        self._twitch = manager._twitch
        self._settings: Settings = manager._twitch.settings

        self._exclude_list = []
        self._priority_list = []

    def set_games(self, games: abc.Iterable[Game]) -> None:
        games_list = sorted(map(str, games))
        self._exclude_list = games_list
        self._priority_list = games_list

    def priorities(self) -> dict[str, int]:
        # NOTE: we shift the indexes so that 0 can be used as the default one
        size = len(self._priority_list)
        return {
            game_name: size - i for i, game_name in enumerate(self._priority_list)
        }


class ProgressHandler:
    def __init__(self):
        self._window = curses.newwin(9, WINDOW_WIDTH, 3, 0)

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

        self._window.addstr(0, 0, _("gui", "progress", "game") + ' ')
        self._window.addstr(self._campaign_game)
        self._window.addstr(1, 0, _("gui", "progress", "campaign") + ' ')
        self._window.addstr(self._campaign_name)
        self._window.addstr(2, 0, _("gui", "progress", "campaign_progress") + ' ')
        self._window.addstr(f"{self._campaign_percentage}")
        self._window.addstr(2, 30, _("gui", "progress", "remaining").format(time=self._campaign_remaining))
        self._window.addstr(3, 0, self._progress_bar(self._campaign_progress, WINDOW_WIDTH))

        self._window.addstr(5, 0, _("gui", "progress", "drop") + ' ')
        self._window.addstr(self._drop_rewards)
        self._window.addstr(6, 0, _("gui", "progress", "drop_progress") + ' ')
        self._window.addstr(f"{self._drop_percentage}")
        self._window.addstr(6, 30, _("gui", "progress", "remaining").format(time=self._drop_remaining))
        self._window.addstr(7, 0, self._progress_bar(self._drop_progress, WINDOW_WIDTH))

        self._window.refresh()


class ConsoleOutput:
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


class ChannelsHandler:
    """
    The channel list is removed from CLI mode
    to reduce unnecessary display space use
    """

    def __init__(self):
        # self._channels: dict[str, dict] = {}
        # self._channel_map: dict[str, Channel] = {}
        # self._selection = None
        pass

    def _set(self, iid: str, column: str, value: any):
        # self._channels[iid][column] = value
        pass

    def _insert(self, iid: str, values: dict[str, any]):
        # self._channels[iid] = values
        pass

    def clear(self):
        # self._channels.clear()
        pass

    def set_watching(self, channel: Channel):
        # self.clear_watching()
        # iid = channel.iid
        # self._channels[iid]["watching"] = True
        pass

    def clear_watching(self):
        # for channel in self._channels.values():
        #     channel["watching"] = False
        pass

    def get_selection(self) -> Channel | None:
        # if not self._channel_map:
        #     return None
        # if not self._selection:
        #     return None
        # return self._channel_map[self._selection]
        pass

    def display(self, channel: Channel, *, add: bool = False):
        # iid = channel.iid
        # if not add and iid not in self._channel_map:
        #     # the channel isn't on the list and we're not supposed to add it
        #     return
        # # ACL-based
        # acl_based = channel.acl_based
        # # status
        # if channel.online:
        #     status = _("gui", "channels", "online")
        # elif channel.pending_online:
        #     status = _("gui", "channels", "pending")
        # else:
        #     status = _("gui", "channels", "offline")
        # # game
        # game = str(channel.game or '')
        # # drops
        # drops = channel.drops_enabled
        # # viewers
        # viewers = ''
        # if channel.viewers is not None:
        #     viewers = channel.viewers
        # # points
        # points = ''
        # if channel.points is not None:
        #     points = channel.points
        # if iid in self._channel_map:
        #     self._set(iid, "game", game)
        #     self._set(iid, "drops", drops)
        #     self._set(iid, "status", status)
        #     self._set(iid, "viewers", viewers)
        #     self._set(iid, "acl_base", acl_based)
        #     if points != '':  # we still want to display 0
        #         self._set(iid, "points", points)
        # elif add:
        #     self._channel_map[iid] = channel
        #     self._insert(
        #         iid,
        #         {
        #             "game": game,
        #             "drops": drops,
        #             "points": points,
        #             "status": status,
        #             "viewers": viewers,
        #             "acl_base": acl_based,
        #             "channel": channel.name,
        #         },
        #     )
        pass


class CLIManager:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._close_requested = asyncio.Event()

        # GUI
        self._stdscr = curses.initscr()

        self.output = ConsoleOutput()
        # register logging handler
        self._handler = _LoggingHandler(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logger = logging.getLogger("TwitchDrops")
        logger.addHandler(self._handler)
        if (logging_level := logger.getEffectiveLevel()) < logging.ERROR:
            self.print(f"Logging level: {logging.getLevelName(logging_level)}")

        self.status = StatusBar()
        self.websockets = WebsocketStatus()
        self.inv = InventoryHandler(self)
        self.login = LoginHandler(self)
        self.progress = ProgressHandler()
        self.channels = ChannelsHandler()
        self.settings = SettingsHandler(self)

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
        """
        Requests the GUI application to close.
        The window itself will be closed in the closing sequence later.
        """
        self._close_requested.set()
        # notify client we're supposed to close
        self._twitch.close()
        return 0

    def close_window(self):
        """
        Closes the window. Invalidates the logger.
        """
        logging.getLogger("TwitchDrops").removeHandler(self._handler)

    def save(self, *, force: bool = False):
        pass

    def set_games(self, games: abc.Iterable[Game]):
        self.settings.set_games(games)

    def display_drop(self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)  # main tab
        # inventory overview is updated from within drops themselves via change events

    def clear_drop(self):
        self.progress.display(None)

    def print(self, message: str):
        self.output.print(message)
