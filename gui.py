from __future__ import annotations

import os
import sys
import asyncio
import logging
import tkinter as tk
from math import log10, ceil
from tkinter.font import Font
from collections import namedtuple, OrderedDict
from tkinter import Tk, ttk, StringVar, DoubleVar
from typing import (
    Any, Optional, List, Dict, Set, Tuple, TypedDict, Iterable, NoReturn, TYPE_CHECKING
)

try:
    import pystray
except ModuleNotFoundError as exc:
    raise ImportError("You have to run 'pip install pystray' first") from exc

from constants import FORMATTER, WS_TOPICS_LIMIT, MAX_WEBSOCKETS, WINDOW_TITLE, State

if TYPE_CHECKING:
    from twitch import Twitch
    from channel import Channel
    from inventory import Game, TimedDrop


digits = ceil(log10(WS_TOPICS_LIMIT))
WS_FONT = ("Courier New", 10)


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class ICOImage:
    def __init__(self, path: str):
        with open(path, 'rb') as file:
            self._data = file.read()

    def save(self, file, format):
        file.write(self._data)


class TKOutputHandler(logging.Handler):
    def __init__(self, output: GUIManager):
        super().__init__()
        self._output = output

    def emit(self, record):
        self._output.print(self.format(record))


class PlaceholderEntry(ttk.Entry):
    def __init__(
        self,
        master: ttk.Widget,
        *args,
        placeholder: str,
        placeholdercolor: str = "grey60",
        **kwargs,
    ):
        super().__init__(master, *args, **kwargs)
        self._show: str = kwargs.get("show", '')
        self._text_color: str = kwargs.get("foreground", '')
        self._ph_color: str = placeholdercolor
        self._ph_text: str = placeholder
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self._ph: bool = False
        self._focus_out(None)

    def _focus_in(self, event):
        """
        On focus in, if we've had a placeholder, clear the box and set normal text colour and show.
        """
        if self._ph:
            self._ph = False
            self.config(foreground=self._text_color, show=self._show)
            self.delete(0, "end")

    def _focus_out(self, event):
        """
        On focus out, if we're empty, insert a placeholder,
        set placeholder text color and make sure it's shown.
        If we're not empty, leave the box as is.
        """
        if not super().get():
            self._ph = True
            self.config(foreground=self._ph_color, show='')
            self.insert(0, self._ph_text)

    def _store_option(self, options: Dict[str, Any], attr: str, name: str):
        value = options.get(name)
        if value is not None:
            setattr(self, attr, value)

    def configure(self, *args, **kwargs):
        if args:
            options = args[0]
        if kwargs:
            options = kwargs
        self._store_option(options, "_show", "show")
        self._store_option(options, "_ph_text", "placeholder")
        self._store_option(options, "_text_color", "foreground")
        self._store_option(options, "_ph_color", "placeholdercolor")
        super().configure(*args, *kwargs)

    def get(self):
        if self._ph:
            return ''
        return super().get()

    def clear(self):
        self.delete(0, "end")
        self._ph = True
        self.config(foreground=self._ph_color, show='')
        self.insert(0, self._ph_text)

    def enable(self):
        super().configure(state="normal")

    def disable(self):
        super().configure(state="disabled")


class _WSEntry(TypedDict):
    status: str
    topics: int


class WebsocketStatus:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._status_var = StringVar()
        self._topics_var = StringVar()
        frame = ttk.LabelFrame(master, text="Websocket Status", padding=(4, 0, 4, 4))
        frame.grid(column=0, row=0, sticky="nsew", padx=2)
        ttk.Label(
            frame,
            text='\n'.join(f"Websocket #{i}:" for i in range(1, MAX_WEBSOCKETS + 1)),
            font=WS_FONT,
        ).grid(column=0, row=0)
        ttk.Label(
            frame,
            textvariable=self._status_var,
            width=16,
            justify="left",
            font=WS_FONT,
        ).grid(column=1, row=0)
        ttk.Label(
            frame,
            textvariable=self._topics_var,
            width=(digits * 2 + 1),
            justify="right",
            font=WS_FONT,
        ).grid(column=2, row=0)
        self._items: Dict[int, Optional[_WSEntry]] = {i: None for i in range(MAX_WEBSOCKETS)}
        self._update()

    def update(self, idx: int, status: Optional[str] = None, topics: Optional[int] = None):
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")
        entry = self._items.get(idx)
        if entry is None:
            entry = self._items[idx] = _WSEntry(status="Disconnected", topics=0)
        if status is not None:
            entry["status"] = status
        if topics is not None:
            entry["topics"] = topics
        self._update()

    def remove(self, idx: int):
        if idx in self._items:
            del self._items[idx]
            self._update()

    def _update(self):
        status_lines: List[str] = []
        topic_lines: List[str] = []
        for idx in range(MAX_WEBSOCKETS):
            item = self._items.get(idx)
            if item is None:
                status_lines.append('')
                topic_lines.append('')
            else:
                status_lines.append(item["status"])
                topic_lines.append(f"{item['topics']:>{digits}}/{WS_TOPICS_LIMIT}")
        self._status_var.set('\n'.join(status_lines))
        self._topics_var.set('\n'.join(topic_lines))


LoginData = namedtuple("LoginData", ["username", "password", "token"])


class LoginForm:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._var = StringVar()
        frame = ttk.LabelFrame(master, text="Login Form", padding=(4, 0, 4, 4))
        frame.grid(column=1, row=0, sticky="nsew", padx=2)
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)
        ttk.Label(frame, text="Status:\nUser ID:").grid(column=0, row=0)
        ttk.Label(frame, textvariable=self._var, justify="center").grid(column=1, row=0)
        self._login_entry = PlaceholderEntry(frame, placeholder="Username")
        self._login_entry.grid(column=0, row=1, columnspan=2)
        self._pass_entry = PlaceholderEntry(frame, placeholder="Password", show='•')
        self._pass_entry.grid(column=0, row=2, columnspan=2)
        self._token_entry = PlaceholderEntry(frame, placeholder="2FA Code (optional)")
        self._token_entry.grid(column=0, row=3, columnspan=2)
        self._confirm = asyncio.Event()
        self._button = ttk.Button(frame, text="Login", command=self._confirm.set, state="disabled")
        self._button.grid(column=0, row=4, columnspan=2)
        self.update("Logged out", None)

    def clear(self, login: bool = False, password: bool = False, token: bool = False):
        clear_all = not login and not password and not token
        if login or clear_all:
            self._login_entry.clear()
        if password or clear_all:
            self._pass_entry.clear()
        if token or clear_all:
            self._token_entry.clear()

    async def ask_login(self) -> LoginData:
        self.update("Login required", None)
        self._manager.print("Please log in to continue.")
        self._confirm.clear()
        self._button.config(state="normal")
        await self._confirm.wait()
        self._button.config(state="disabled")
        data = LoginData(self._login_entry.get(), self._pass_entry.get(), self._token_entry.get())
        return data

    def update(self, status: str, user_id: Optional[int]):
        if user_id is not None:
            user_str = str(user_id)
        else:
            user_str = "-"
        self._var.set(f"{status}\n{user_str}")


class GameSelector:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._var = StringVar()
        frame = ttk.LabelFrame(master, text="Game Selector", padding=(4, 0, 4, 4))
        frame.grid(column=1, row=1, sticky="nsew", padx=2)
        frame.columnconfigure(0, weight=1)
        self._list = tk.Listbox(
            frame,
            height=5,
            selectmode="single",
            activestyle="none",
            exportselection=False,
            highlightthickness=0,
        )
        self._list.pack(fill="both", expand=True)
        self._selection: Optional[str] = self._manager._twitch.options.game
        self._games: OrderedDict[str, Game] = OrderedDict()
        self._list.bind("<<ListboxSelect>>", self._on_select)

    def set_games(self, games: Iterable[Game]):
        self._games.clear()
        self._games.update((str(g), g) for g in games)
        self._list.delete(0, "end")
        self._list.insert("end", *self._games.keys())
        self._list.config(width=0)  # autoadjust listbox width
        if self._selection is not None:
            selected_index: Optional[int] = next(
                (
                    i
                    for i, str_game in enumerate(self._games.keys())
                    if str_game == self._selection
                ),
                None,
            )
            if selected_index is not None:
                # reselect the currently selected item
                self._list.selection_clear(0, "end")
                self._list.selection_set(selected_index)
            else:
                # the game we've had selected isn't there anymore - clear selection
                self._selection = None

    def _on_select(self, event):
        current = self._list.curselection()
        print(current)
        if not current:
            # can happen when the user clicks on an empty list
            new_selection = None
        else:
            new_selection = self._list.get(current[0])
        if new_selection != self._selection:
            self._selection = new_selection
            self._manager._twitch.change_state(State.GAME_SELECT)

    def get_selection(self) -> Optional[Game]:
        if self._selection is None:
            return None
        return self._games[self._selection]

    def set_first(self) -> Game:
        # select and return the first game from the list
        self._list.selection_clear(0, "end")
        self._list.selection_set(0)
        for game_name, first_game in self._games.items():
            # just one iteration to get, set and return the first game
            self._selection = game_name
            return first_game
        raise RuntimeError("No games to select from")


class _BaseVars(TypedDict):
    progress: DoubleVar
    percentage: StringVar
    remaining: StringVar


class _CampaignVars(_BaseVars):
    name: StringVar


class _DropVars(_BaseVars):
    rewards: StringVar


class _ProgressVars(TypedDict):
    campaign: _CampaignVars
    drop: _DropVars


class CampaignProgress:
    BAR_LENGTH = 240

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._vars: _ProgressVars = {
            "campaign": {
                "name": StringVar(),  # campaign name
                "progress": DoubleVar(),  # controls the progress bar
                "percentage": StringVar(),  # percentage display string
                "remaining": StringVar(),  # time remaining string
            },
            "drop": {
                "rewards": StringVar(),  # drop rewards
                "progress": DoubleVar(),  # as above
                "percentage": StringVar(),  # as above
                "remaining": StringVar(),  # as above
            },
        }
        self._frame = frame = ttk.LabelFrame(
            master, text="Campaign Progress", padding=(4, 0, 4, 4)
        )
        frame.grid(column=0, row=1, sticky="nsew", padx=2)
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Campaign:").grid(column=0, row=0, columnspan=2)
        ttk.Label(
            frame, textvariable=self._vars["campaign"]["name"]
        ).grid(column=0, row=1, columnspan=2)
        ttk.Label(frame, text="Progress:").grid(column=0, row=2, rowspan=2)
        ttk.Label(frame, textvariable=self._vars["campaign"]["percentage"]).grid(column=1, row=2)
        ttk.Label(frame, textvariable=self._vars["campaign"]["remaining"]).grid(column=1, row=3)
        ttk.Progressbar(
            frame,
            mode="determinate",
            length=self.BAR_LENGTH,
            maximum=1,
            variable=self._vars["campaign"]["progress"],
        ).grid(column=0, row=4, columnspan=2)
        ttk.Separator(
            frame, orient="horizontal"
        ).grid(row=5, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Label(frame, text="Drop:").grid(column=0, row=6, columnspan=2)
        ttk.Label(
            frame, textvariable=self._vars["drop"]["rewards"]
        ).grid(column=0, row=7, columnspan=2)
        ttk.Label(frame, text="Progress:").grid(column=0, row=8, rowspan=2)
        ttk.Label(frame, textvariable=self._vars["drop"]["percentage"]).grid(column=1, row=8)
        ttk.Label(frame, textvariable=self._vars["drop"]["remaining"]).grid(column=1, row=9)
        ttk.Progressbar(
            frame,
            mode="determinate",
            length=self.BAR_LENGTH,
            maximum=1,
            variable=self._vars["drop"]["progress"],
        ).grid(column=0, row=10, columnspan=2)
        self._drop: Optional[TimedDrop] = None
        self._timer_task: Optional[asyncio.Task[None]] = None
        self._update_time(0)

    @staticmethod
    def _divmod(minutes: int, seconds: int) -> Tuple[int, int]:
        if seconds < 60 and minutes > 0:
            minutes -= 1
        hours, minutes = divmod(minutes, 60)
        return (hours, minutes)

    def _update_time(self, seconds: int):
        drop = self._drop
        if drop is not None:
            drop_minutes = drop.remaining_minutes
            campaign_minutes = drop.campaign.remaining_minutes
        else:
            drop_minutes = 0
            campaign_minutes = 0
        drop_vars: _DropVars = self._vars["drop"]
        campaign_vars: _CampaignVars = self._vars["campaign"]
        dseconds = seconds % 60
        hours, minutes = self._divmod(drop_minutes, seconds)
        drop_vars["remaining"].set(f"{hours:>2}:{minutes:02}:{dseconds:02} remaining")
        hours, minutes = self._divmod(campaign_minutes, seconds)
        campaign_vars["remaining"].set(f"{hours:>2}:{minutes:02}:{dseconds:02} remaining")

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

    def display(self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False):
        self._drop = drop
        # drop update
        vars_drop = self._vars["drop"]
        vars_drop["rewards"].set(drop.rewards_text())
        vars_drop["progress"].set(drop.progress)
        vars_drop["percentage"].set(f"{drop.progress:6.1%}")
        # campaign update
        campaign = drop.campaign
        vars_campaign = self._vars["campaign"]
        vars_campaign["name"].set(campaign.name)
        vars_campaign["progress"].set(campaign.progress)
        vars_campaign["percentage"].set(
            f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
        )
        # tray
        tray = self._manager.tray
        tray.display_progress(drop)
        self.stop_timer()
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


class ConsoleOutput:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        frame = ttk.LabelFrame(master, text="Output", padding=(4, 0, 4, 4))
        frame.grid(column=0, row=2, columnspan=2, sticky="nsew", padx=2)
        frame.rowconfigure(0, weight=1)  # let the frame expand
        frame.columnconfigure(0, weight=1)
        # tell master frame that the containing row can expand
        master.rowconfigure(2, weight=1)
        xscroll = ttk.Scrollbar(frame, orient="horizontal")
        yscroll = ttk.Scrollbar(frame, orient="vertical")
        self._text = tk.Text(
            frame,
            width=52,
            height=10,
            wrap="none",
            state="disabled",
            exportselection=False,
            xscrollcommand=xscroll.set,
            yscrollcommand=yscroll.set,
        )
        xscroll.config(command=self._text.xview)
        yscroll.config(command=self._text.yview)
        self._text.grid(column=0, row=0, sticky="nsew")
        xscroll.grid(column=0, row=1, sticky="ew")
        yscroll.grid(column=1, row=0, sticky="ns")

    def print(self, *values, sep: str = ' ', end: str = '\n'):
        self._text.config(state="normal")
        self._text.insert("end", f"{sep.join(values)}{end}")
        self._text.see("end")  # scroll to the newly added line
        self._text.config(state="disabled")


class Buttons(TypedDict):
    frame: ttk.Frame
    switch: ttk.Button
    load_points: ttk.Button


class ChannelList:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        frame = ttk.LabelFrame(master, text="Channels", padding=(4, 0, 4, 4))
        frame.grid(column=0, row=1, sticky="nsew", padx=2)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        # tell master frame that the containing column and row can expand
        master.columnconfigure(0, weight=1)
        master.rowconfigure(1, weight=1)
        buttons_frame = ttk.Frame(frame)
        self._buttons: Buttons = {
            "frame": buttons_frame,
            "switch": ttk.Button(
                buttons_frame,
                text="Switch",
                state="disabled",
                command=manager._twitch.state_change(State.CHANNEL_SWITCH),
            ),
            "load_points": ttk.Button(
                buttons_frame, text="Load Points", command=self._load_points
            ),
        }
        buttons_frame.grid(column=0, row=0, columnspan=2)
        self._buttons["switch"].grid(column=0, row=0)
        self._buttons["load_points"].grid(column=1, row=0)
        scroll = ttk.Scrollbar(frame, orient="vertical")
        self._table = table = ttk.Treeview(
            frame,
            # columns definition is updated by _add_column
            yscrollcommand=scroll.set,
        )
        scroll.config(command=table.yview)
        table.grid(column=0, row=1, sticky="nsew")
        scroll.grid(column=1, row=1, sticky="ns")
        self._font = Font(frame, manager._style.lookup("Treeview", "font"))
        self._const_width: Set[str] = set()
        table.tag_configure("watching", background="gray70")
        table.bind("<Button-1>", self._disable_column_resize)
        table.bind("<<TreeviewSelect>>", self._selected)
        self._add_column("#0", '', width=0)
        self._add_column("channel", "Channel", width=100, anchor='w')
        self._add_column("status", "Status", width_template="OFFLINE ❌")
        self._add_column("game", "Game", width=50)
        self._add_column("drops", "🎁", width_template="✔")
        self._add_column("viewers", "Viewers", width_template="1234567")
        self._add_column("points", "Points", width_template="1234567")
        self._add_column("priority", "❗", width_template="✔")
        self._channel_map: Dict[str, Channel] = {}

    def _add_column(
        self,
        cid: str,
        name: str,
        *,
        anchor: tk._Anchor = "center",
        width: Optional[int] = None,
        width_template: Optional[str] = None,
    ):
        table = self._table
        # we need to save the column settings and headings before modifying the columns...
        columns: Tuple[str, ...] = table.cget("columns") or ()
        column_settings: Dict[str, Tuple[str, tk._Anchor, int, int]] = {}
        for s_cid in columns:
            s_column = table.column(s_cid)
            assert s_column is not None
            s_heading = table.heading(s_cid)
            assert s_heading is not None
            column_settings[s_cid] = (
                s_heading["text"], s_heading["anchor"], s_column["width"], s_column["minwidth"]
            )
        # ..., then add the column, but ensure we're not adding the icons column...
        if cid != "#0":
            table.config(columns=columns + (cid,))
        # ..., and then restore column settings and headings afterwards
        for s_cid, (s_name, s_anchor, s_width, s_minwidth) in column_settings.items():
            table.heading(s_cid, text=s_name, anchor=s_anchor)
            table.column(s_cid, minwidth=s_minwidth, width=s_width, stretch=False)
        # set heading and column settings for the new column
        if width_template is not None:
            width = self._measure(width_template)
            self._const_width.add(cid)
        assert width is not None
        table.heading(cid, text=name, anchor=anchor)
        table.column(cid, minwidth=width, width=width, stretch=False)

    def _disable_column_resize(self, event):
        if self._table.identify_region(event.x, event.y) == "separator":
            return "break"

    def _selected(self, event):
        selection = self._table.selection()
        if selection:
            self._buttons["switch"].config(state="normal")
        else:
            self._buttons["switch"].config(state="disabled")

    def _load_points(self):
        # disable the button afterwards
        self._buttons["load_points"].config(state="disabled")
        asyncio.gather(*(ch.claim_bonus() for ch in self._manager._twitch.channels.values()))

    def _measure(self, text: str) -> int:
        # we need this because columns have 9-10 pixels of padding that cuts text off
        return self._font.measure(text) + 10

    def _redraw(self):
        # this forces a redraw that recalculates widget width
        self._table.event_generate("<<ThemeChanged>>")

    def _adjust_width(self, column: str, value: str):
        # causes the column to expand if the value's width is greater than the current width
        if column in self._const_width:
            return
        value_width = self._measure(value)
        curr_width = self._table.column(column, "width")
        if value_width > curr_width:
            self._table.column(column, width=value_width)
            self._redraw()

    def shrink(self):
        # causes the columns to shrink back after long values have been removed from it
        columns = self._table.cget("columns")
        iids = self._table.get_children()
        for column in columns:
            if column in self._const_width:
                continue
            if iids:
                # table haa at least one item
                width = max(self._measure(self._table.set(i, column)) for i in iids)
                self._table.column(column, width=width)
            else:
                # no items - use minwidth
                minwidth = self._table.column(column, "minwidth")
                self._table.column(column, width=minwidth)
        self._redraw()

    def _set(self, iid: str, column: str, value: str):
        self._table.set(iid, column, value)
        self._adjust_width(column, value)

    def _insert(self, iid: str, values: Dict[str, str]):
        to_insert: List[str] = []
        for cid in self._table.cget("columns"):
            value = values[cid]
            to_insert.append(value)
            self._adjust_width(cid, value)
        self._table.insert(parent='', index="end", iid=iid, values=to_insert)

    def clear_watching(self):
        for iid in self._table.tag_has("watching"):
            self._table.item(iid, tags='')

    def set_watching(self, channel: Channel):
        self.clear_watching()
        iid = channel.iid
        self._table.item(iid, tags="watching")
        self._table.see(iid)

    def get_selection(self) -> Optional[Channel]:
        if not self._channel_map:
            return None
        selection = self._table.selection()
        if not selection:
            return None
        return self._channel_map[selection[0]]

    def clear_selection(self):
        self._table.selection_set('')

    def clear(self):
        iids = self._table.get_children()
        self._table.delete(*iids)

    def display(self, channel: Channel, *, add: bool = False):
        # priority
        priority = "✔" if channel.priority else "❌"
        # status
        if channel.online:
            status = "ONLINE  ✔"
        elif channel.pending_online:
            status = "OFFLINE ⏳"
        else:
            status = "OFFLINE ❌"
        # game
        game = str(channel.game or '')
        # drops
        drops = "✔" if channel.drops_enabled else "❌"
        # viewers
        viewers = ''
        if channel.viewers is not None:
            viewers = str(channel.viewers)
        # points
        points = ''
        if channel.points is not None:
            points = str(channel.points)
        iid = channel.iid
        if iid in self._channel_map:
            self._set(iid, "game", game)
            self._set(iid, "drops", drops)
            self._set(iid, "status", status)
            self._set(iid, "viewers", viewers)
            self._set(iid, "priority", priority)
            if points != '':  # we still want to display 0
                self._set(iid, "points", points)
        elif add:
            self._channel_map[iid] = channel
            self._insert(
                iid,
                {
                    "game": game,
                    "drops": drops,
                    "points": points,
                    "status": status,
                    "viewers": viewers,
                    "priority": priority,
                    "channel": channel.name,
                },
            )

    def remove(self, channel: Channel):
        iid = channel.iid
        del self._channel_map[iid]
        self._table.delete(iid)


class TrayIcon:
    TITLE = "Twitch Drops Miner"

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self.icon: Optional[pystray.Icon] = None
        self._button = ttk.Button(master, command=self.minimize, text="Minimize to Tray")
        self._button.grid(column=0, row=0, sticky="e")
        if manager._twitch.options.tray:
            # start hidden in tray
            self._manager._root.after_idle(self.minimize)

    def is_tray(self) -> bool:
        return self.icon is not None

    def get_title(self, drop: Optional[TimedDrop]) -> str:
        if drop is None:
            return self.TITLE
        return (
            f"{self.TITLE}\n"
            f"{drop.rewards_text()}: {drop.progress:.1%} "
            f"({drop.campaign.claimed_drops}/{drop.campaign.total_drops})"
        )

    def start(self):
        if self.icon is None:
            loop = asyncio.get_running_loop()
            drop = self._manager.progress._drop

            # we need this because tray icon lives in a separate thread
            def bridge(func):
                return lambda: loop.call_soon_threadsafe(func)

            menu = pystray.Menu(
                pystray.MenuItem("Show", bridge(self.restore), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", bridge(self.quit)),
            )
            self.icon = pystray.Icon(
                "twitch_miner",
                ICOImage(resource_path("pickaxe.ico")),
                self.get_title(drop),
                menu,
            )
            self.icon.run_detached()

    def stop(self):
        if self.icon is not None:
            self.icon.stop()
            self.icon = None

    def quit(self):
        self.stop()
        self._manager.close()

    def minimize(self):
        if not self.is_tray():
            self.start()
            self._manager._root.withdraw()

    def restore(self):
        if self.is_tray():
            self.stop()
            self._manager._root.deiconify()

    def notify(self, message: str, title: Optional[str] = None, duration: float = 10):
        if self.icon is not None:
            icon = self.icon

            async def notifier():
                icon.notify(message, title)
                await asyncio.sleep(duration)
                icon.remove_notification()

            asyncio.create_task(notifier())

    def display_progress(self, drop: TimedDrop):
        if self.icon is not None:
            self.icon.title = self.get_title(drop)


class GUIManager:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._poll_task: Optional[asyncio.Task[NoReturn]] = None
        self._closed = asyncio.Event()
        self._root = root = Tk()
        # withdraw immediately to prevent the window from flashing
        self._root.withdraw()
        root.resizable(False, True)
        root.iconbitmap(resource_path("pickaxe.ico"))  # window icon
        root.title(WINDOW_TITLE)  # window title
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<KeyPress-Escape>", self.unfocus)
        self._style = ttk.Style(root)
        self._style.map(
            "Treeview",
            foreground=self._fixed_map("foreground"),
            background=self._fixed_map("background"),
        )
        main_frame = ttk.Frame(root, padding=8)
        main_frame.grid(sticky="nsew")
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        self.websockets = WebsocketStatus(self, main_frame)
        self.login = LoginForm(self, main_frame)
        self.progress = CampaignProgress(self, main_frame)
        self.games = GameSelector(self, main_frame)
        self.output = ConsoleOutput(self, main_frame)
        second_frame = ttk.Frame(main_frame)
        second_frame.grid(column=2, row=0, rowspan=3, sticky="nsew")
        main_frame.columnconfigure(2, weight=1)
        self.tray = TrayIcon(self, second_frame)
        self.channels = ChannelList(self, second_frame)
        # clamp minimum window height (update first, so that geometry calculates the size)
        root.update_idletasks()
        root.minsize(width=0, height=root.winfo_reqheight())
        # register logging handler
        self._handler = TKOutputHandler(self)
        self._handler.setFormatter(FORMATTER)
        logging.getLogger("TwitchDrops").addHandler(self._handler)
        # show the window when ready
        if not self._twitch.options.tray:
            self._root.deiconify()

    # https://stackoverflow.com/questions/56329342/tkinter-treeview-background-tag-not-working
    def _fixed_map(self, option):
        # Fix for setting text colour for Tkinter 8.6.9
        # From: https://core.tcl.tk/tk/info/509cafafae
        #
        # Returns the style map for 'option' with any styles starting with
        # ('!disabled', '!selected', ...) filtered out.

        # style.map() returns an empty list for missing options, so this
        # should be future-safe.
        return [
            elm for elm in self._style.map("Treeview", query_opt=option)
            if elm[:2] != ("!disabled", "!selected")
        ]

    @property
    def running(self) -> bool:
        return self._poll_task is not None

    @property
    def close_requested(self) -> bool:
        return self._closed.is_set()

    def start(self):
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll())
        # self.progress.start_timer()

    def stop(self):
        self.progress.stop_timer()
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    async def _poll(self):
        """
        This runs the Tkinter event loop via asyncio instead of calling mainloop.
        0.05s gives similar performance and CPU usage.
        Not ideal, but the simplest way to avoid threads, thread safety,
        loop.call_soon_threadsafe, futures and all of that.
        """
        update = self._root.update
        while True:
            try:
                update()
            except tk.TclError:
                # root has been destroyed
                break
            await asyncio.sleep(0.05)
        self._poll_task = None

    def close(self):
        """
        Requests the application to close.
        The window itself will be closed in the closing sequence later.
        """
        self._closed.set()
        # notify client we're supposed to close
        self._twitch.request_close()

    def close_window(self):
        """
        Closes the window. Invalidates the logger.
        """
        self._root.destroy()
        logging.getLogger("TwitchDrops").removeHandler(self._handler)

    def unfocus(self, event):
        # support pressing ESC to unfocus
        self._root.focus_set()
        self.channels.clear_selection()

    def prevent_close(self):
        self._closed.clear()

    async def wait_until_closed(self):
        # wait until the user closes the window
        await self._closed.wait()

    def print(self, *args, **kwargs):
        # print to our custom output
        self.output.print(*args, **kwargs)


if __name__ == "__main__":
    # Everything below is for debug purposes only
    from functools import partial
    from types import SimpleNamespace

    class StrNamespace(SimpleNamespace):
        def __str__(self):
            if hasattr(self, "_str__"):
                return self._str__(self)
            return super().__str__()

    def create_game(id: int, name: str):
        return StrNamespace(name=name, id=id, _str__=lambda s: s.name)

    iid = 0

    def create_channel(
        name: str,
        status: int,
        game: Optional[str],
        drops: bool,
        viewers: int,
        points: int,
        priority: bool,
    ):
        # status: 0 -> OFFLINE, 1 -> PENDING_ONLINE, 2 -> ONLINE
        if status == 1:
            status = False
            pending = True
        else:
            pending = False
        if game is not None:
            game_obj: Optional[StrNamespace] = create_game(0, game)
        else:
            game_obj = None
        global iid
        return SimpleNamespace(
            name=name,
            iid=(iid := iid + 1),
            points=points,
            online=bool(status),
            pending_online=pending,
            game=game_obj,
            drops_enabled=drops,
            viewers=viewers,
            priority=priority,
        )

    def create_drop(
        campaign_name: str,
        rewards: str,
        claimed_drops: int,
        total_drops: int,
        current_minutes: int,
        total_minutes: int,
    ):
        cd = claimed_drops
        td = total_drops
        cm = current_minutes
        tm = total_minutes
        mock = SimpleNamespace(
            id="0",
            campaign=SimpleNamespace(
                name=campaign_name,
                timed_drops={},
                claimed_drops=cd,
                total_drops=td,
                remaining_drops=td - cd,
                progress=(cd * tm + cm) / (td * tm),
                remaining_minutes=(td - cd) * tm - cm,
            ),
            rewards_text=lambda: rewards,
            progress=cm/tm,
            current_minutes=cm,
            required_minutes=tm,
            remaining_minutes=tm-cm,
        )
        mock.campaign.timed_drops["0"] = mock
        return mock

    async def main(exit_event: asyncio.Event):
        # Initialize GUI debug
        mock = SimpleNamespace(options=SimpleNamespace(game=None, tray=False), channels={})
        mock.change_state = lambda state: mock.gui.print(f"State change: {state.value}")
        mock.state_change = lambda state: partial(mock.change_state, state)
        gui = GUIManager(mock)  # type: ignore
        mock.gui = gui
        mock.request_close = gui.stop
        gui.start()
        assert gui._poll_task is not None
        gui._poll_task.add_done_callback(lambda t: exit_event.set())
        # Login form
        gui.login.update("Login required", None)
        # Game selector
        gui.games.set_games([
            create_game(123456, "Best Game"),
            # create_game(654321, "My Game Very Long Name"),
        ])
        # Channel list
        gui.channels.display(
            create_channel(
                name="Thomus", status=0, game=None, drops=False, viewers=0, points=0, priority=True
            )
        )
        channel = create_channel(
            name="Traitus", status=1, game=None, drops=False, viewers=0, points=0, priority=True
        )
        gui.channels.display(channel)
        gui.channels.set_watching(channel)
        gui.channels.display(
            create_channel(
                name="Testus",
                status=2,
                game="Best Game",
                drops=True,
                viewers=42,
                points=1234567,
                priority=False,
            )
        )
        gui.channels.display(
            create_channel(
                name="Livus",
                status=2,
                game="Best Game",
                drops=True,
                viewers=69,
                points=1234567,
                priority=False,
            )
        )
        gui._root.update()
        gui.channels.get_selection()
        # Tray
        # gui.tray.minimize()
        await asyncio.sleep(1)
        gui.tray.notify("Bounty Coins (3/7)", "Mined Drop")
        # Drop progress
        drop = create_drop("Wardrobe Cleaning", "Fancy Pants", 2, 7, 239, 240)
        gui.progress.display(drop)
        await asyncio.sleep(63)
        drop.current_minutes = 240
        drop.remaining_minutes = 0
        drop.progress = 1.0
        campaign = drop.campaign
        campaign.remaining_minutes -= 1
        campaign.progress = 3/7
        campaign.claimed_drops = 3
        campaign.remaining_drops = 4
        gui.progress.display(drop)
        await asyncio.sleep(10)
        drop.current_minutes = 0
        drop.remaining_minutes = 240
        drop.progress = 0.0
        gui.progress.display(drop)

    loop = asyncio.get_event_loop()
    exit_event = asyncio.Event()
    loop.create_task(main(exit_event))
    loop.run_until_complete(exit_event.wait())
