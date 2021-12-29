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
from typing import Any, Optional, List, Dict, Set, TypedDict, Iterable, NoReturn, TYPE_CHECKING

from version import __version__
from constants import WS_TOPICS_LIMIT, MAX_WEBSOCKETS, State

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


class TKOutputHandler(logging.Handler):
    def __init__(self, output: GUIManager):
        super().__init__()
        self._output = output

    def emit(self, record):
        self._output.print(self.format(record))


class PlaceholderEntry(ttk.Entry):
    def __init__(
        self,
        master,
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
    def __init__(self, manager: GUIManager, master: tk.Misc):
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
    def __init__(self, manager: GUIManager, master: tk.Misc):
        self._manager = manager
        self._var = StringVar()
        frame = ttk.LabelFrame(master, text="Login Form", padding=(4, 0, 4, 4))
        frame.grid(column=1, row=0, sticky="nsew", padx=2)
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)
        ttk.Label(frame, text=("Status:\nUser ID:")).grid(column=0, row=0)
        ttk.Label(frame, textvariable=self._var, justify="center").grid(column=1, row=0)
        self._login_entry = PlaceholderEntry(frame, placeholder="Username")
        self._login_entry.grid(column=0, row=1, columnspan=2)
        self._pass_entry = PlaceholderEntry(frame, placeholder="Password", show='•')
        self._pass_entry.grid(column=0, row=2, columnspan=2)
        self._token_entry = PlaceholderEntry(frame, placeholder="2FA Code")
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

    def enable(
        self,
        login: Optional[bool] = None,
        password: Optional[bool] = None,
        token: Optional[bool] = None,
        button: Optional[bool] = None,
    ):
        if login is not None:
            if login:
                self._login_entry.enable()
            else:
                self._login_entry.disable()
        if password is not None:
            if password:
                self._pass_entry.enable()
            else:
                self._pass_entry.disable()
        if token is not None:
            if token:
                self._token_entry.enable()
            else:
                self._token_entry.disable()
        if button is not None:
            if button:
                self._button.config(state="normal")
            else:
                self._button.config(state="disabled")

    async def ask_login(self) -> LoginData:
        self._manager.print("Please log in.")
        self._confirm.clear()
        self.enable(button=True)
        await self._confirm.wait()
        self.enable(button=False)
        data = LoginData(self._login_entry.get(), self._pass_entry.get(), self._token_entry.get())
        return data

    def update(self, status: str, user_id: Optional[int]):
        if user_id is not None:
            user_str = str(user_id)
        else:
            user_str = "-"
        self._var.set(f"{status}\n{user_str}")


class GameSelector:
    def __init__(self, manager: GUIManager, master: tk.Misc):
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
        self._selection: Optional[str] = self._manager._twitch._options.game
        self._games: OrderedDict[str, Game] = OrderedDict()
        self._list.bind("<<ListboxSelect>>", self._on_select)

    @property
    def selected(self) -> Optional[str]:
        return self._selection

    def set_games(self, games: Iterable[Game]):
        self._games.clear()
        self._games.update((str(g), g) for g in sorted(games, key=lambda g: g.name))
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
                self._list.selection_set(selected_index)
            else:
                # the game we've had selected isn't there anymore - clear selection
                self._selection = None

    def _on_select(self, event):
        current = self._list.curselection()
        if not current:
            # can happen when the user clicks on an empty list
            self._selection = None
        else:
            self._selection = self._list.get(current[0])

    def get_selection(self) -> Game:
        if self._selection is None:
            if not self._games:
                raise RuntimeError("No games to select from")
            # select and return the first game from the list
            self._list.selection_set(0)
            first_game = next(iter(self._games.values()))
            self._selection = str(first_game)
            return first_game
        return self._games[self._selection]

    def get_next_selection(self) -> Optional[Game]:
        current = self._list.curselection()
        if not current:
            return self.get_selection()
        game_name = self._list.get(current[0]+1)
        if game_name:
            return self._games[game_name]
        else:
            # this was the last game on the list
            return None


class _BaseVars(TypedDict):
    progress: DoubleVar
    percentage: StringVar
    remaining: StringVar
    minutes: int


class _CampaignVars(_BaseVars):
    name: StringVar


class _DropVars(_BaseVars):
    rewards: StringVar


class _ProgressVars(TypedDict):
    campaign: _CampaignVars
    drop: _DropVars
    seconds: int


class CampaignProgress:
    BAR_LENGTH = 240

    def __init__(self, manager: GUIManager, master: tk.Misc):
        self._vars: _ProgressVars = {
            "campaign": {
                "name": StringVar(),  # campaign name
                "progress": DoubleVar(),  # controls the progress bar
                "percentage": StringVar(),  # percentage display string
                "remaining": StringVar(),  # time remaining string
                "minutes": 0,  # remaining minutes
            },
            "drop": {
                "rewards": StringVar(),  # drop rewards
                "progress": DoubleVar(),  # as above
                "percentage": StringVar(),  # as above
                "remaining": StringVar(),  # as above
                "minutes": 0,  # as above
            },
            "seconds": 1,  # remaining seconds (common for both campaign and drop)
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
        self._timer_task: Optional[asyncio.Task[None]] = None
        self._update_time()

    def _update_time(self) -> bool:
        # read vars
        minutes_changed: bool = False
        seconds: int = self._vars["seconds"]
        drop_vars: _DropVars = self._vars["drop"]
        campaign_vars: _CampaignVars = self._vars["campaign"]
        drop_minutes: int = drop_vars["minutes"]
        campaign_minutes: int = campaign_vars["minutes"]
        # handle seconds
        if seconds <= 0:
            if drop_minutes > 0:
                drop_minutes -= 1
                minutes_changed = True
            if campaign_minutes > 0:
                campaign_minutes -= 1
                minutes_changed = True
            if minutes_changed:
                seconds = 60
        if seconds > 0:
            seconds -= 1
        # display time
        hours, minutes = divmod(drop_minutes, 60)
        drop_vars["remaining"].set(f"{hours:>2}:{minutes:02}:{seconds:02} remaining")
        hours, minutes = divmod(campaign_minutes, 60)
        campaign_vars["remaining"].set(f"{hours:>2}:{minutes:02}:{seconds:02} remaining")
        # store back
        self._vars["seconds"] = seconds
        if minutes_changed:
            drop_vars["minutes"] = drop_minutes
            campaign_vars["minutes"] = campaign_minutes
        # if there's no time left, stop the loop
        if campaign_minutes + drop_minutes + seconds > 0:
            return True
        return False

    async def _timer_loop(self):
        run = self._update_time()
        while run:
            await asyncio.sleep(1)
            run = self._update_time()
        self._timer_task = None

    def start_timer(self):
        if self._timer_task is None:
            self._vars["seconds"] = 1
            self._timer_task = asyncio.create_task(self._timer_loop())

    def stop_timer(self):
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    def restart_timer(self):
        self.stop_timer()
        self.start_timer()

    def update(self, drop: TimedDrop):
        # campaign update
        campaign = drop.campaign
        vars_campaign = self._vars["campaign"]
        vars_campaign["name"].set(campaign.name)
        vars_campaign["progress"].set(campaign.progress)
        vars_campaign["percentage"].set(
            f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
        )
        vars_campaign["minutes"] = campaign.remaining_minutes
        # drop update
        vars_drop = self._vars["drop"]
        vars_drop["rewards"].set(drop.rewards_text())
        vars_drop["progress"].set(drop.progress)
        vars_drop["percentage"].set(f"{drop.progress:6.1%}")
        vars_drop["minutes"] = drop.remaining_minutes
        # reschedule our seconds update timer
        self.restart_timer()


class ConsoleOutput:
    def __init__(self, manager: GUIManager, master: tk.Misc):
        frame = ttk.LabelFrame(master, text="Output", padding=(4, 0, 4, 4))
        frame.grid(column=0, row=2, columnspan=2, sticky="nsew", padx=2)
        frame.rowconfigure(0, weight=1)  # let the frame expand
        frame.columnconfigure(0, weight=1)
        master.rowconfigure(2, weight=1)  # tell master frame that the containing row can expand
        xscroll = ttk.Scrollbar(frame, orient="horizontal")
        yscroll = ttk.Scrollbar(frame, orient="vertical")
        self._text = tk.Text(
            frame,
            exportselection=False,
            height=10,
            width=52,
            wrap="none",
            state="disabled",
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
    cleanup: ttk.Button
    switch: ttk.Button
    load_points: ttk.Button


class ChannelList:
    def __init__(self, manager: GUIManager, master: tk.Misc):
        self._manager = manager
        frame = ttk.LabelFrame(master, text="Channels", padding=(4, 0, 4, 4))
        frame.grid(column=2, row=0, rowspan=3, sticky="nsew", padx=2)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        # tell master frame that the containing column can expand
        master.columnconfigure(2, weight=1)
        buttons_frame = ttk.Frame(frame)
        self._buttons: Buttons = {
            "frame": buttons_frame,
            "cleanup": ttk.Button(
                buttons_frame,
                text="Cleanup",
                command=manager._twitch.state_change(State.CHANNEL_CLEANUP),
            ),
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
        self._buttons["cleanup"].grid(column=0, row=0)
        self._buttons["switch"].grid(column=1, row=0)
        self._buttons["load_points"].grid(column=2, row=0)
        scroll = ttk.Scrollbar(frame, orient="vertical")
        self._table = table = ttk.Treeview(
            frame,
            columns=("channel", "status", "game", "viewers", "points"),
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
        self._column("#0", '', width=0)
        self._column("channel", "Channel", width=100, anchor='w')
        self._column("status", "Status", width_template="OFFLINE ❌")
        self._column("game", "Game", width=50)
        self._column("viewers", "Viewers", width_template="0000000")
        self._column("points", "Points", width_template="0000000")
        self._channel_map: Dict[str, Channel] = {}

    def _column(
        self,
        cid: str,
        name: str,
        *,
        anchor: str = "center",
        width: Optional[int] = None,
        width_template: Optional[str] = None,
    ):
        if width_template is not None:
            width = self._measure(width_template)
            self._const_width.add(cid)
        assert width is not None
        self._table.column(cid, width=width, stretch=False)
        self._table.heading(cid, text=name, anchor=anchor)

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

    def _adjust_width(self, column: str, value: str):
        # causes the column to expand if the value's width is greater than the current width
        if column in self._const_width:
            return
        value_width = self._measure(value)
        curr_width = self._table.column(column, "width")
        if value_width > curr_width:
            self._table.column(column, minwidth=value_width, width=value_width)
            self._table.event_generate("<<ThemeChanged>>")  # force redraw

    def _set(self, iid: str, column: str, value: str):
        self._table.set(iid, column, value)
        self._adjust_width(column, value)

    def _insert(self, iid: str, *args: str):
        self._table.insert(parent='', index="end", iid=iid, values=args)
        for column, value in zip(self._table.cget("columns"), args):
            self._adjust_width(column, value)

    def clear_watching(self):
        for iid in self._table.tag_has("watching"):
            self._table.item(iid, tags='')

    def set_watching(self, channel: Channel):
        self.clear_watching()
        self._table.item(channel.iid, tags="watching")

    def get_selection(self) -> Optional[Channel]:
        if not self._channel_map:
            return None
        selection = self._table.selection()
        if not selection:
            return None
        return self._channel_map[selection[0]]

    def clear_selection(self):
        self._table.selection_set('')

    def display(self, channel: Channel):
        # status
        if channel.online:
            status_str = "ONLINE  ✅"
        elif channel.pending_online:
            status_str = "OFFLINE ⏰"
        else:
            status_str = "OFFLINE ❌"
        # game
        game_str = str(channel.game or '')
        # viewers
        viewers_str = ''
        if channel.viewers is not None:
            viewers_str = str(channel.viewers)
        # points
        points_str = ''
        if channel.points is not None:
            points_str = str(channel.points)
        iid = channel.iid
        if self._table.exists(iid):
            self._set(iid, "status", status_str)
            self._set(iid, "game", game_str)
            self._set(iid, "viewers", viewers_str)
            if points_str:
                self._set(iid, "points", points_str)
        else:
            self._channel_map[iid] = channel
            self._insert(iid, channel.name, status_str, game_str, viewers_str, points_str)

    def remove(self, channel: Channel):
        iid = channel.iid
        del self._channel_map[iid]
        self._table.delete(iid)


class GUIManager:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._poll_task: Optional[asyncio.Task[NoReturn]] = None
        self._closed = asyncio.Event()
        self._root = root = Tk()
        root.resizable(False, True)
        root.iconbitmap(resource_path("pickaxe.ico"))  # window icon
        root.title(f"Twitch Drops Miner v{__version__} (by DevilXD)")  # window title
        root.protocol("WM_DELETE_WINDOW", self._on_close)
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
        self.channels = ChannelList(self, main_frame)
        # clamp minimum window height (update first, so that geometry calculates the size)
        root.update_idletasks()
        root.minsize(width=0, height=root.winfo_reqheight())
        # register logging handler
        handler = TKOutputHandler(self)
        handler.setFormatter(
            logging.Formatter("{asctime}: {levelname}: {message}", style='{', datefmt="%H:%M:%S")
        )
        logging.getLogger("TwitchDrops").addHandler(handler)

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
            update()
            await asyncio.sleep(0.05)

    def unfocus(self, event):
        self._root.focus_set()
        self.channels.clear_selection()

    def _on_close(self):
        self._closed.set()
        # notify client we're supposed to close
        self._twitch.request_close()

    def prevent_close(self):
        self._closed.clear()

    async def wait_until_closed(self):
        # wait until the user closes the window
        await self._closed.wait()

    def close(self):
        self.stop()
        if self._root is not None:
            self._root.destroy()
        self._closed.set()

    def print(self, *args, **kwargs):
        # print to our custom output
        self.output.print(*args, **kwargs)


if __name__ == "__main__":
    # Everything below is for debug purposes only
    from types import SimpleNamespace

    class StrNamespace(SimpleNamespace):
        def __str__(self):
            if hasattr(self, "_str__"):
                return self._str__(self)
            return super().__str__()

    def state_change(state: State):
        def changer(state: State = state):
            gui.print(f"State change: {state.value}")
        return changer

    gui: GUIManager
    mock = SimpleNamespace(
        _options=SimpleNamespace(game=None),
        state_change=state_change,
    )
    gui = GUIManager(mock)  # type: ignore
    mock.request_close = gui._root.destroy

    def create_game(id: int, name: str):
        return StrNamespace(name=name, id=id, _str__=lambda s: s.name)

    iid = 0

    def create_channel(name: str, online: int, game: Optional[str], viewers: int, points: int):
        if online == 1:
            online = False
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
            online=bool(online),
            pending_online=pending,
            game=game_obj,
            viewers=viewers,
        )

    # Game selctor
    gui.games.set_games([
        create_game(491115, "Paladins"),
        create_game(460630, "Tom Clancy's Rainbow Six Siege"),
    ])
    game = gui.games.get_next_selection()
    game = gui.games.get_next_selection()
    game = gui.games.get_next_selection()
    # Channel list
    gui.channels.display(create_channel("PaladinsGame", 0, None, 0, 0))
    channel = create_channel("Traitus", 1, None, 0, 0)
    gui.channels.display(channel)
    gui.channels.display(create_channel("Testus", 2, "Paladins", 42, 1234567))
    gui.channels.set_watching(channel)
    gui._root.update()
    gui.channels.get_selection()
    gui._root.mainloop()
