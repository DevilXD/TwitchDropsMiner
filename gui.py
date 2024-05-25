from __future__ import annotations

import os
import re
import sys
import ctypes
import asyncio
import logging
import tkinter as tk
from pathlib import Path
from collections import abc
from textwrap import dedent
from math import log10, ceil
from dataclasses import dataclass
from tkinter.font import Font, nametofont
from functools import partial, cached_property
from datetime import datetime, timedelta, timezone
from tkinter import Tk, ttk, StringVar, DoubleVar, IntVar
from typing import Any, Union, Tuple, TypedDict, NoReturn, Generic, TYPE_CHECKING

import pystray
from yarl import URL
from PIL.ImageTk import PhotoImage
from PIL import Image as Image_module

if sys.platform == "win32":
    import win32api
    import win32con
    import win32gui

from cache import CurrentSeconds
from translate import _
from cache import ImageCache
from exceptions import ExitRequest
from utils import resource_path, set_root_icon, webopen, Game, _T
from constants import (
    SELF_PATH, OUTPUT_FORMATTER, WS_TOPICS_LIMIT, MAX_WEBSOCKETS, WINDOW_TITLE, State
)
if sys.platform == "win32":
    from registry import RegistryKey, ValueType


if TYPE_CHECKING:
    from twitch import Twitch
    from channel import Channel
    from settings import Settings
    from inventory import DropsCampaign, TimedDrop


TK_PADDING = Union[int, Tuple[int, int], Tuple[int, int, int], Tuple[int, int, int, int]]
DIGITS = ceil(log10(WS_TOPICS_LIMIT))


######################
# GUI ELEMENTS START #
######################


class _TKOutputHandler(logging.Handler):
    def __init__(self, output: GUIManager):
        super().__init__()
        self._output = output

    def emit(self, record):
        self._output.print(self.format(record))


class PlaceholderEntry(ttk.Entry):
    def __init__(
        self,
        master: ttk.Widget,
        *args: Any,
        placeholder: str,
        prefill: str = '',
        placeholdercolor: str = "grey60",
        **kwargs: Any,
    ):
        super().__init__(master, *args, **kwargs)
        self._prefill: str = prefill
        self._show: str = kwargs.get("show", '')
        self._text_color: str = kwargs.get("foreground", '')
        self._ph_color: str = placeholdercolor
        self._ph_text: str = placeholder
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        if isinstance(self, ttk.Combobox):
            # only bind this for comboboxes
            self.bind("<<ComboboxSelected>>", self._combobox_select)
        self._ph: bool = False
        self._insert_placeholder()

    def _insert_placeholder(self) -> None:
        """
        If we're empty, insert a placeholder, set placeholder text color and make sure it's shown.
        If we're not empty, leave the box as is.
        """
        if not super().get():
            self._ph = True
            super().config(foreground=self._ph_color, show='')
            super().insert("end", self._ph_text)

    def _remove_placeholder(self) -> None:
        """
        If we've had a placeholder, clear the box and set normal text colour and show.
        """
        if self._ph:
            self._ph = False
            super().delete(0, "end")
            super().config(foreground=self._text_color, show=self._show)
            if self._prefill:
                super().insert("end", self._prefill)

    def _focus_in(self, event: tk.Event[PlaceholderEntry]) -> None:
        self._remove_placeholder()

    def _focus_out(self, event: tk.Event[PlaceholderEntry]) -> None:
        self._insert_placeholder()

    def _combobox_select(self, event: tk.Event[PlaceholderEntry]):
        # combobox clears and inserts the selected value internally, bypassing the insert method.
        # disable the placeholder flag and set the color here, so _focus_in doesn't clear the entry
        self._ph = False
        super().config(foreground=self._text_color, show=self._show)

    def _store_option(
        self, options: dict[str, object], name: str, attr: str, *, remove: bool = False
    ) -> None:
        if name in options:
            if remove:
                value = options.pop(name)
            else:
                value = options[name]
            setattr(self, attr, value)

    def configure(self, *args: Any, **kwargs: Any) -> Any:
        options: dict[str, Any] = {}
        if args and args[0] is not None:
            options.update(args[0])
        if kwargs:
            options.update(kwargs)
        self._store_option(options, "show", "_show")
        self._store_option(options, "foreground", "_text_color")
        self._store_option(options, "placeholder", "_ph_text", remove=True)
        self._store_option(options, "prefill", "_prefill", remove=True)
        self._store_option(options, "placeholdercolor", "_ph_color", remove=True)
        return super().configure(**kwargs)

    def config(self, *args: Any, **kwargs: Any) -> Any:
        # because 'config = configure' makes mypy complain
        self.configure(*args, **kwargs)

    def get(self) -> str:
        if self._ph:
            return ''
        return super().get()

    def insert(self, index: tk._EntryIndex, content: str) -> None:
        # when inserting into the entry externally, disable the placeholder flag
        if not content:
            # if an empty string was passed in
            return
        self._remove_placeholder()
        super().insert(index, content)

    def delete(self, first: tk._EntryIndex, last: tk._EntryIndex | None = None) -> None:
        super().delete(first, last)
        self._insert_placeholder()

    def clear(self) -> None:
        self.delete(0, "end")

    def replace(self, content: str) -> None:
        super().delete(0, "end")
        self.insert("end", content)


class PlaceholderCombobox(PlaceholderEntry, ttk.Combobox):
    pass


class PaddedListbox(tk.Listbox):
    def __init__(self, master: ttk.Widget, *args, padding: TK_PADDING = (0, 0, 0, 0), **kwargs):
        # we place the listbox inside a frame with the same background
        # this means we need to forward the 'grid' method to the frame, not the listbox
        self._frame = tk.Frame(master)
        self._frame.rowconfigure(0, weight=1)
        self._frame.columnconfigure(0, weight=1)
        super().__init__(self._frame)
        # mimic default listbox style with sunken relief and borderwidth of 1
        if "relief" not in kwargs:
            kwargs["relief"] = "sunken"
        if "borderwidth" not in kwargs:
            kwargs["borderwidth"] = 1
        self.configure(*args, padding=padding, **kwargs)

    def grid(self, *args, **kwargs):
        return self._frame.grid(*args, **kwargs)

    def grid_remove(self) -> None:
        return self._frame.grid_remove()

    def grid_info(self) -> tk._GridInfo:
        return self._frame.grid_info()

    def grid_forget(self) -> None:
        return self._frame.grid_forget()

    def configure(self, *args: Any, **kwargs: Any) -> Any:
        options: dict[str, Any] = {}
        if args and args[0] is not None:
            options.update(args[0])
        if kwargs:
            options.update(kwargs)
        # NOTE on processed options:
        # • relief is applied to the frame only
        # • background is copied, so that both listbox and frame change color
        # • borderwidth is applied to the frame only
        # bg is folded into background for easier processing
        if "bg" in options:
            options["background"] = options.pop("bg")
        frame_options = {}
        if "relief" in options:
            frame_options["relief"] = options.pop("relief")
        if "background" in options:
            frame_options["background"] = options["background"]  # copy
        if "borderwidth" in options:
            frame_options["borderwidth"] = options.pop("borderwidth")
        self._frame.configure(frame_options)
        # update padding
        if "padding" in options:
            padding: TK_PADDING = options.pop("padding")
            padx1: tk._ScreenUnits
            padx2: tk._ScreenUnits
            pady1: tk._ScreenUnits
            pady2: tk._ScreenUnits
            if not isinstance(padding, tuple) or len(padding) == 1:
                if isinstance(padding, tuple):
                    padding = padding[0]
                padx1 = padx2 = pady1 = pady2 = padding
            elif len(padding) == 2:
                padx1 = padx2 = padding[0]
                pady1 = pady2 = padding[1]
            elif len(padding) == 3:
                padx1, padx2 = padding[0], padding[1]
                pady1 = pady2 = padding[2]  # type: ignore
            else:
                padx1, padx2, pady1, pady2 = padding  # type: ignore
            super().grid(column=0, row=0, padx=(padx1, padx2), pady=(pady1, pady2), sticky="nsew")
        else:
            super().grid(column=0, row=0, sticky="nsew")
        # listbox uses flat relief to blend in with the inside of the frame
        options["relief"] = "flat"
        return super().configure(options)

    def config(self, *args: Any, **kwargs: Any) -> Any:
        # because 'config = configure' makes mypy complain
        self.configure(*args, **kwargs)


class MouseOverLabel(ttk.Label):
    def __init__(self, *args, alt_text: str = '', reverse: bool = False, **kwargs) -> None:
        self._org_text: str = ''
        self._alt_text: str = ''
        self._alt_reverse: bool = reverse
        self._bind_enter: str | None = None
        self._bind_leave: str | None = None
        super().__init__(*args, **kwargs)
        self.configure(text=kwargs.get("text", ''), alt_text=alt_text, reverse=reverse)

    def _set_org(self, event: tk.Event[MouseOverLabel]):
        super().config(text=self._org_text)

    def _set_alt(self, event: tk.Event[MouseOverLabel]):
        super().config(text=self._alt_text)

    def configure(self, *args: Any, **kwargs: Any) -> Any:
        options: dict[str, Any] = {}
        if args and args[0] is not None:
            options.update(args[0])
        if kwargs:
            options.update(kwargs)
        applicable_options: set[str] = set((
            "text",
            "reverse",
            "alt_text",
        ))
        if applicable_options.intersection(options.keys()):
            # we need to pop some options, because they can't be passed down to the label,
            # as that will result in an error later down the line
            events_change: bool = False
            if "text" in options:
                if bool(self._org_text) != bool(options["text"]):
                    events_change = True
                self._org_text = options["text"]
            if "alt_text" in options:
                if bool(self._alt_text) != bool(options["alt_text"]):
                    events_change = True
                self._alt_text = options.pop("alt_text")
            if "reverse" in options:
                if bool(self._alt_reverse) != bool(options["reverse"]):
                    events_change = True
                self._alt_reverse = options.pop("reverse")
            if self._org_text and not self._alt_text:
                options["text"] = self._org_text
            elif (not self._org_text or self._alt_reverse) and self._alt_text:
                options["text"] = self._alt_text
            if events_change:
                if self._bind_enter is not None:
                    self.unbind(self._bind_enter)
                    self._bind_enter = None
                if self._bind_leave is not None:
                    self.unbind(self._bind_leave)
                    self._bind_leave = None
                if self._org_text and self._alt_text:
                    if self._alt_reverse:
                        self._bind_enter = self.bind("<Enter>", self._set_org)
                        self._bind_leave = self.bind("<Leave>", self._set_alt)
                    else:
                        self._bind_enter = self.bind("<Enter>", self._set_alt)
                        self._bind_leave = self.bind("<Leave>", self._set_org)
        return super().configure(options)

    def config(self, *args: Any, **kwargs: Any) -> Any:
        # because 'config = configure' makes mypy complain
        self.configure(*args, **kwargs)


class LinkLabel(ttk.Label):
    def __init__(self, *args, link: str, **kwargs) -> None:
        self._link: str = link
        # style provides font and foreground color
        if "style" not in kwargs:
            kwargs["style"] = "Link.TLabel"
        elif not kwargs["style"]:
            super().__init__(*args, **kwargs)
            return
        if "cursor" not in kwargs:
            kwargs["cursor"] = "hand2"
        if "padding" not in kwargs:
            # W, N, E, S
            kwargs["padding"] = (0, 2, 0, 2)
        super().__init__(*args, **kwargs)
        self.bind("<ButtonRelease-1>", lambda e: webopen(self._link))


class SelectMenu(tk.Menubutton, Generic[_T]):
    def __init__(
        self,
        master: tk.Misc,
        *args: Any,
        tearoff: bool = False,
        options: dict[str, _T],
        command: abc.Callable[[_T], Any] | None = None,
        default: str | None = None,
        relief: tk._Relief = "solid",
        **kwargs: Any,
    ):
        width = max((len(k) for k in options.keys()), default=20)
        super().__init__(
            master, *args, relief=relief, width=width, **kwargs
        )
        self._menu_options: dict[str, _T] = options
        self._command = command
        self.menu = tk.Menu(self, tearoff=tearoff)
        self.config(menu=self.menu)
        for name in options.keys():
            self.menu.add_command(label=name, command=partial(self._select, name))
        if default is not None and default in self._menu_options:
            self.config(text=default)

    def _select(self, option: str) -> None:
        self.config(text=option)
        if self._command is not None:
            self._command(self._menu_options[option])

    def get(self) -> _T:
        return self._menu_options[self.cget("text")]


###########################################
# GUI ELEMENTS END / GUI DEFINITION START #
###########################################


class StatusBar:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        frame = ttk.LabelFrame(master, text=_("gui", "status", "name"), padding=(4, 0, 4, 4))
        frame.grid(column=0, row=0, columnspan=3, sticky="nsew", padx=2)
        self._label = ttk.Label(frame)
        self._label.grid(column=0, row=0, sticky="nsew")

    def update(self, text: str):
        self._label.config(text=text)

    def clear(self):
        self._label.config(text='')


class _WSEntry(TypedDict):
    status: str
    topics: int


class WebsocketStatus:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        frame = ttk.LabelFrame(master, text=_("gui", "websocket", "name"), padding=(4, 0, 4, 4))
        frame.grid(column=0, row=1, sticky="nsew", padx=2)
        self._status_var = StringVar(frame)
        self._topics_var = StringVar(frame)
        ttk.Label(
            frame,
            text='\n'.join(
                _("gui", "websocket", "websocket").format(id=i)
                for i in range(1, MAX_WEBSOCKETS + 1)
            ),
            style="MS.TLabel",
        ).grid(column=0, row=0)
        ttk.Label(
            frame,
            textvariable=self._status_var,
            width=16,
            justify="left",
            style="MS.TLabel",
        ).grid(column=1, row=0)
        ttk.Label(
            frame,
            textvariable=self._topics_var,
            width=(DIGITS * 2 + 1),
            justify="right",
            style="MS.TLabel",
        ).grid(column=2, row=0)
        self._items: dict[int, _WSEntry | None] = {i: None for i in range(MAX_WEBSOCKETS)}
        self._update()

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")
        entry = self._items.get(idx)
        if entry is None:
            entry = self._items[idx] = _WSEntry(
                status=_("gui", "websocket", "disconnected"), topics=0
            )
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
        status_lines: list[str] = []
        topic_lines: list[str] = []
        for idx in range(MAX_WEBSOCKETS):
            if (item := self._items.get(idx)) is None:
                status_lines.append('')
                topic_lines.append('')
            else:
                status_lines.append(item["status"])
                topic_lines.append(f"{item['topics']:>{DIGITS}}/{WS_TOPICS_LIMIT}")
        self._status_var.set('\n'.join(status_lines))
        self._topics_var.set('\n'.join(topic_lines))


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class LoginForm:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._var = StringVar(master)
        frame = ttk.LabelFrame(master, text=_("gui", "login", "name"), padding=(4, 0, 4, 4))
        frame.grid(column=1, row=1, sticky="nsew", padx=2)
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)
        ttk.Label(frame, text=_("gui", "login", "labels")).grid(column=0, row=0)
        ttk.Label(frame, textvariable=self._var, justify="center").grid(column=1, row=0)
        self._login_entry = PlaceholderEntry(frame, placeholder=_("gui", "login", "username"))
        # self._login_entry.grid(column=0, row=1, columnspan=2)
        self._pass_entry = PlaceholderEntry(
            frame, placeholder=_("gui", "login", "password"), show='•'
        )
        # self._pass_entry.grid(column=0, row=2, columnspan=2)
        self._token_entry = PlaceholderEntry(frame, placeholder=_("gui", "login", "twofa_code"))
        # self._token_entry.grid(column=0, row=3, columnspan=2)

        self._confirm = asyncio.Event()
        self._button = ttk.Button(
            frame, text=_("gui", "login", "button"), command=self._confirm.set, state="disabled"
        )
        self._button.grid(column=0, row=4, columnspan=2)
        self.update(_("gui", "login", "logged_out"), None)

    def clear(self, login: bool = False, password: bool = False, token: bool = False):
        clear_all = not login and not password and not token
        if login or clear_all:
            self._login_entry.clear()
        if password or clear_all:
            self._pass_entry.clear()
        if token or clear_all:
            self._token_entry.clear()

    async def wait_for_login_press(self) -> None:
        self._confirm.clear()
        try:
            self._button.config(state="normal")
            await self._manager.coro_unless_closed(self._confirm.wait())
        finally:
            self._button.config(state="disabled")

    async def ask_login(self) -> LoginData:
        self.update(_("gui", "login", "required"), None)
        # ensure the window isn't hidden into tray when this runs
        self._manager.grab_attention(sound=False)
        while True:
            self._manager.print(_("gui", "login", "request"))
            await self.wait_for_login_press()
            login_data = LoginData(
                self._login_entry.get().strip(),
                self._pass_entry.get(),
                self._token_entry.get().strip(),
            )
            # basic input data validation: 3-25 characters in length, only ascii and underscores
            if (
                not 3 <= len(login_data.username) <= 25
                and re.match(r'^[a-zA-Z0-9_]+$', login_data.username)
            ):
                self.clear(login=True)
                continue
            if len(login_data.password) < 8:
                self.clear(password=True)
                continue
            if login_data.token and len(login_data.token) < 6:
                self.clear(token=True)
                continue
            return login_data

    async def ask_enter_code(self, user_code: str) -> None:
        self.update(_("gui", "login", "required"), None)
        # ensure the window isn't hidden into tray when this runs
        self._manager.grab_attention(sound=False)
        self._manager.print(_("gui", "login", "request"))
        await self.wait_for_login_press()
        self._manager.print(f"Enter this code on the Twitch's device activation page: {user_code}")
        webopen("https://www.twitch.tv/activate")

    def update(self, status: str, user_id: int | None):
        if user_id is not None:
            user_str = str(user_id)
        else:
            user_str = "-"
        self._var.set(f"{status}\n{user_str}")


class _BaseVars(TypedDict):
    progress: DoubleVar
    percentage: StringVar
    remaining: StringVar


class _CampaignVars(_BaseVars):
    name: StringVar
    game: StringVar


class _DropVars(_BaseVars):
    rewards: StringVar


class _ProgressVars(TypedDict):
    campaign: _CampaignVars
    drop: _DropVars


class CampaignProgress:
    BAR_LENGTH = 420

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._vars: _ProgressVars = {
            "campaign": {
                "name": StringVar(master),  # campaign name
                "game": StringVar(master),  # game name
                "progress": DoubleVar(master),  # controls the progress bar
                "percentage": StringVar(master),  # percentage display string
                "remaining": StringVar(master),  # time remaining string, filled via _update_time
            },
            "drop": {
                "rewards": StringVar(master),  # drop rewards
                "progress": DoubleVar(master),  # as above
                "percentage": StringVar(master),  # as above
                "remaining": StringVar(master),  # as above
            },
        }
        self._frame = frame = ttk.LabelFrame(
            master, text=_("gui", "progress", "name"), padding=(4, 0, 4, 4)
        )
        frame.grid(column=0, row=2, columnspan=2, sticky="nsew", padx=2)
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=1)
        game_campaign = ttk.Frame(frame)
        game_campaign.grid(column=0, row=0, columnspan=2, sticky="nsew")
        game_campaign.columnconfigure(0, weight=1)
        game_campaign.columnconfigure(1, weight=1)
        ttk.Label(game_campaign, text=_("gui", "progress", "game")).grid(column=0, row=0)
        ttk.Label(game_campaign, textvariable=self._vars["campaign"]["game"]).grid(column=0, row=1)
        ttk.Label(game_campaign, text=_("gui", "progress", "campaign")).grid(column=1, row=0)
        ttk.Label(game_campaign, textvariable=self._vars["campaign"]["name"]).grid(column=1, row=1)
        ttk.Label(
            frame, text=_("gui", "progress", "campaign_progress")
        ).grid(column=0, row=2, rowspan=2)
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
        ttk.Label(frame, text=_("gui", "progress", "drop")).grid(column=0, row=6, columnspan=2)
        ttk.Label(
            frame, textvariable=self._vars["drop"]["rewards"]
        ).grid(column=0, row=7, columnspan=2)
        ttk.Label(
            frame, text=_("gui", "progress", "drop_progress")
        ).grid(column=0, row=8, rowspan=2)
        ttk.Label(frame, textvariable=self._vars["drop"]["percentage"]).grid(column=1, row=8)
        ttk.Label(frame, textvariable=self._vars["drop"]["remaining"]).grid(column=1, row=9)
        ttk.Progressbar(
            frame,
            mode="determinate",
            length=self.BAR_LENGTH,
            maximum=1,
            variable=self._vars["drop"]["progress"],
        ).grid(column=0, row=10, columnspan=2)
        self._drop: TimedDrop | None = None
        self._timer_task: asyncio.Task[None] | None = None
        self.display(None)

    @staticmethod
    def _divmod(minutes: int, seconds: int) -> tuple[int, int]:
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
        CurrentSeconds.set_current_seconds(dseconds)
        hours, minutes = self._divmod(drop_minutes, seconds)
        drop_vars["remaining"].set(
            _("gui", "progress", "remaining").format(time=f"{hours:>2}:{minutes:02}:{dseconds:02}")
        )
        hours, minutes = self._divmod(campaign_minutes, seconds)
        campaign_vars["remaining"].set(
            _("gui", "progress", "remaining").format(time=f"{hours:>2}:{minutes:02}:{dseconds:02}")
        )

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
        vars_drop = self._vars["drop"]
        vars_campaign = self._vars["campaign"]
        self.stop_timer()
        if drop is None:
            # clear the drop display
            vars_drop["rewards"].set("...")
            vars_drop["progress"].set(0.0)
            vars_drop["percentage"].set("-%")
            vars_campaign["name"].set("...")
            vars_campaign["game"].set("...")
            vars_campaign["progress"].set(0.0)
            vars_campaign["percentage"].set("-%")
            self._update_time(0)
            return
        vars_drop["rewards"].set(drop.rewards_text())
        vars_drop["progress"].set(drop.progress)
        vars_drop["percentage"].set(f"{drop.progress:6.1%}")
        campaign = drop.campaign
        vars_campaign["name"].set(campaign.name)
        vars_campaign["game"].set(campaign.game.name)
        vars_campaign["progress"].set(campaign.progress)
        vars_campaign["percentage"].set(
            f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
        )
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
        frame = ttk.LabelFrame(master, text=_("gui", "output"), padding=(4, 0, 4, 4))
        frame.grid(column=0, row=3, columnspan=3, sticky="nsew", padx=2)
        # tell master frame that the containing row can expand
        master.rowconfigure(3, weight=1)
        frame.rowconfigure(0, weight=1)  # let the frame expand
        frame.columnconfigure(0, weight=1)
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

    def print(self, message: str):
        stamp = datetime.now().strftime("%X")
        if '\n' in message:
            message = message.replace('\n', f"\n{stamp}: ")
        self._text.config(state="normal")
        self._text.insert("end", f"{stamp}: {message}\n")
        self._text.see("end")  # scroll to the newly added line
        self._text.config(state="disabled")


class _Buttons(TypedDict):
    frame: ttk.Frame
    switch: ttk.Button
    load_points: ttk.Button


class ChannelList:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        frame = ttk.LabelFrame(master, text=_("gui", "channels", "name"), padding=(4, 0, 4, 4))
        frame.grid(column=2, row=1, rowspan=2, sticky="nsew", padx=2)
        # tell master frame that the containing column can expand
        master.columnconfigure(2, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        buttons_frame = ttk.Frame(frame)
        self._buttons: _Buttons = {
            "frame": buttons_frame,
            "switch": ttk.Button(
                buttons_frame,
                text=_("gui", "channels", "switch"),
                state="disabled",
                command=manager._twitch.state_change(State.CHANNEL_SWITCH),
            ),
            "load_points": ttk.Button(
                buttons_frame, text=_("gui", "channels", "load_points"), command=self._load_points
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
        self._const_width: set[str] = set()
        table.tag_configure("watching", background="gray70")
        table.bind("<Button-1>", self._disable_column_resize)
        table.bind("<<TreeviewSelect>>", self._selected)
        self._add_column("#0", '', width=0)
        self._add_column(
            "channel", _("gui", "channels", "headings", "channel"), width=100, anchor='w'
        )
        self._add_column(
            "status",
            _("gui", "channels", "headings", "status"),
            width_template=[
                _("gui", "channels", "online"),
                _("gui", "channels", "pending"),
                _("gui", "channels", "offline"),
            ],
        )
        self._add_column("game", _("gui", "channels", "headings", "game"), width=50)
        self._add_column("drops", "🎁", width_template="✔")
        self._add_column(
            "viewers", _("gui", "channels", "headings", "viewers"), width_template="1234567"
        )
        self._add_column(
            "points", _("gui", "channels", "headings", "points"), width_template="1234567"
        )
        self._add_column("acl_base", "📋", width_template="✔")
        self._channel_map: dict[str, Channel] = {}

    def _add_column(
        self,
        cid: str,
        name: str,
        *,
        anchor: tk._Anchor = "center",
        width: int | None = None,
        width_template: str | list[str] | None = None,
    ):
        table = self._table
        # NOTE: we don't do this for the icon column
        if cid != "#0":
            # we need to save the column settings and headings before modifying the columns...
            columns: tuple[str, ...] = table.cget("columns") or ()
            column_settings: dict[str, tuple[str, tk._Anchor, int, int]] = {}
            for s_cid in columns:
                s_column = table.column(s_cid)
                assert s_column is not None
                s_heading = table.heading(s_cid)
                assert s_heading is not None
                column_settings[s_cid] = (
                    s_heading["text"], s_heading["anchor"], s_column["width"], s_column["minwidth"]
                )
            # ..., then add the column
            table.config(columns=columns + (cid,))
            # ..., and then restore column settings and headings afterwards
            for s_cid, (s_name, s_anchor, s_width, s_minwidth) in column_settings.items():
                table.heading(s_cid, text=s_name, anchor=s_anchor)
                table.column(s_cid, minwidth=s_minwidth, width=s_width, stretch=False)
        # set heading and column settings for the new column
        if width_template is not None:
            if isinstance(width_template, str):
                width = self._measure(width_template)
            else:
                width = max((self._measure(template) for template in width_template), default=20)
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
                # table has at least one item
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

    def _insert(self, iid: str, values: dict[str, str]):
        to_insert: list[str] = []
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

    def get_selection(self) -> Channel | None:
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
        self._channel_map.clear()
        self.shrink()

    def display(self, channel: Channel, *, add: bool = False):
        iid = channel.iid
        if not add and iid not in self._channel_map:
            # the channel isn't on the list and we're not supposed to add it
            return
        # ACL-based
        acl_based = "✔" if channel.acl_based else "❌"
        # status
        if channel.online:
            status = _("gui", "channels", "online")
        elif channel.pending_online:
            status = _("gui", "channels", "pending")
        else:
            status = _("gui", "channels", "offline")
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
        if iid in self._channel_map:
            self._set(iid, "game", game)
            self._set(iid, "drops", drops)
            self._set(iid, "status", status)
            self._set(iid, "viewers", viewers)
            self._set(iid, "acl_base", acl_based)
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
                    "acl_base": acl_based,
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
        self.icon: pystray.Icon | None = None
        self.icon_image = Image_module.open(resource_path("pickaxe.ico"))
        self._button = ttk.Button(master, command=self.minimize, text=_("gui", "tray", "minimize"))
        self._button.grid(column=0, row=0, sticky="ne")

    def __del__(self) -> None:
        self.stop()
        self.icon_image.close()

    def get_title(self, drop: TimedDrop | None) -> str:
        if drop is None:
            return self.TITLE
        campaign = drop.campaign
        return (
            f"{self.TITLE}\n"
            f"{campaign.game.name}\n"
            f"{drop.rewards_text()} "
            f"{drop.progress:.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
        )

    def _start(self):
        loop = asyncio.get_running_loop()
        drop = self._manager.progress._drop

        # we need this because tray icon lives in a separate thread
        def bridge(func):
            return lambda: loop.call_soon_threadsafe(func)

        menu = pystray.Menu(
            pystray.MenuItem(_("gui", "tray", "show"), bridge(self.restore), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_("gui", "tray", "quit"), bridge(self.quit)),
        )
        self.icon = pystray.Icon("twitch_miner", self.icon_image, self.get_title(drop), menu)
        # self.icon.run_detached()
        loop.run_in_executor(None, self.icon.run)

    def stop(self):
        if self.icon is not None:
            self.icon.stop()
            self.icon = None

    def quit(self):
        self._manager.close()

    def minimize(self):
        if self.icon is None:
            self._start()
        else:
            self.icon.visible = True
        self._manager._root.withdraw()

    def restore(self):
        if self.icon is not None:
            # self.stop()
            self.icon.visible = False
        self._manager._root.deiconify()

    def notify(
        self, message: str, title: str | None = None, duration: float = 10
    ) -> asyncio.Task[None] | None:
        # do nothing if the user disabled notifications
        if not self._manager._twitch.settings.tray_notifications:
            return None
        if self.icon is not None:
            icon = self.icon  # nonlocal scope bind

            async def notifier():
                icon.notify(message, title)
                await asyncio.sleep(duration)
                icon.remove_notification()

            return asyncio.create_task(notifier())
        return None

    def update_title(self, drop: TimedDrop | None):
        if self.icon is not None:
            self.icon.title = self.get_title(drop)


class Notebook:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._nb = ttk.Notebook(master)
        self._nb.grid(column=0, row=0, sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        # prevent entries from being selected after switching tabs
        self._nb.bind("<<NotebookTabChanged>>", lambda event: manager._root.focus_set())

    def add_tab(self, widget: ttk.Widget, *, name: str, **kwargs):
        kwargs.pop("text", None)
        if "sticky" not in kwargs:
            kwargs["sticky"] = "nsew"
        self._nb.add(widget, text=name, **kwargs)

    def current_tab(self) -> int:
        return self._nb.index("current")

    def add_view_event(self, callback: abc.Callable[[tk.Event[ttk.Notebook]], Any]):
        self._nb.bind("<<NotebookTabChanged>>", callback, True)


class CampaignDisplay(TypedDict):
    frame: ttk.Frame
    status: ttk.Label


class InventoryOverview:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._cache: ImageCache = manager._cache
        self._settings: Settings = manager._twitch.settings
        self._filters = {
            "not_linked": IntVar(master, 1),
            "upcoming": IntVar(master, 1),
            "expired": IntVar(master, 0),
            "excluded": IntVar(master, 0),
            "finished": IntVar(master, 0),
        }
        manager.tabs.add_view_event(self._on_tab_switched)
        # Filtering options
        filter_frame = ttk.LabelFrame(
            master, text=_("gui", "inventory", "filter", "name"), padding=(4, 0, 4, 4)
        )
        LABEL_SPACING = 20
        filter_frame.grid(column=0, row=0, columnspan=2, sticky="nsew")
        ttk.Label(
            filter_frame, text=_("gui", "inventory", "filter", "show"), padding=(0, 0, 10, 0)
        ).grid(column=0, row=0)
        icolumn = 0
        ttk.Checkbutton(
            filter_frame, variable=self._filters["not_linked"]
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "not_linked"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Checkbutton(
            filter_frame, variable=self._filters["upcoming"]
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "upcoming"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Checkbutton(
            filter_frame, variable=self._filters["expired"]
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "expired"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Checkbutton(
            filter_frame, variable=self._filters["excluded"]
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "excluded"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Checkbutton(
            filter_frame, variable=self._filters["finished"]
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "finished"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Button(
            filter_frame, text=_("gui", "inventory", "filter", "refresh"), command=self.refresh
        ).grid(column=(icolumn := icolumn + 1), row=0)
        # Inventory view
        self._canvas = tk.Canvas(master, scrollregion=(0, 0, 0, 0))
        self._canvas.grid(column=0, row=1, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        xscroll = ttk.Scrollbar(master, orient="horizontal", command=self._canvas.xview)
        xscroll.grid(column=0, row=2, sticky="ew")
        yscroll = ttk.Scrollbar(master, orient="vertical", command=self._canvas.yview)
        yscroll.grid(column=1, row=1, sticky="ns")
        self._canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self._canvas.bind("<Configure>", self._canvas_update)
        self._main_frame = ttk.Frame(self._canvas)
        self._canvas.bind(
            "<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        )
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))
        self._canvas.create_window(0, 0, anchor="nw", window=self._main_frame)
        self._campaigns: dict[DropsCampaign, CampaignDisplay] = {}
        self._drops: dict[str, MouseOverLabel] = {}

    def _update_visibility(self, campaign: DropsCampaign):
        # True if the campaign is supposed to show, False makes it hidden.
        frame = self._campaigns[campaign]["frame"]
        not_linked = bool(self._filters["not_linked"].get())
        expired = bool(self._filters["expired"].get())
        excluded = bool(self._filters["excluded"].get())
        upcoming = bool(self._filters["upcoming"].get())
        finished = bool(self._filters["finished"].get())
        priority_only = self._settings.priority_only
        if (
            (not_linked or campaign.linked)
            and (campaign.active or upcoming and campaign.upcoming or expired and campaign.expired)
            and (
                excluded or (
                    campaign.game.name not in self._settings.exclude
                    and not priority_only or campaign.game.name in self._settings.priority
                )
            )
            and (finished or not campaign.finished)
        ):
            frame.grid()
        else:
            frame.grid_remove()

    def _on_tab_switched(self, event: tk.Event[ttk.Notebook]) -> None:
        if self._manager.tabs.current_tab() == 1:
            # refresh only if we're switching to the tab
            self.refresh()

    def refresh(self):
        for campaign in self._campaigns:
            # status
            status_label = self._campaigns[campaign]["status"]
            status_text, status_color = self.get_status(campaign)
            status_label.config(text=status_text, foreground=status_color)
            # visibility
            self._update_visibility(campaign)
        self._canvas_update()

    def _canvas_update(self, event: tk.Event[tk.Canvas] | None = None):
        self._canvas.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_mousewheel(self, event: tk.Event[tk.Misc]):
        delta = -1 if event.delta > 0 else 1
        state: int = event.state if isinstance(event.state, int) else 0
        if state & 1:
            scroll = self._canvas.xview_scroll
        else:
            scroll = self._canvas.yview_scroll
        scroll(delta, "units")

    async def add_campaign(self, campaign: DropsCampaign) -> None:
        campaign_frame = ttk.Frame(self._main_frame, relief="ridge", borderwidth=1, padding=4)
        campaign_frame.grid(column=0, row=len(self._campaigns), sticky="nsew", pady=3)
        campaign_frame.rowconfigure(4, weight=1)
        campaign_frame.columnconfigure(1, weight=1)
        campaign_frame.columnconfigure(3, weight=10000)
        # Name
        ttk.Label(
            campaign_frame, text=campaign.name, takefocus=False, width=45
        ).grid(column=0, row=0, columnspan=2, sticky="w")
        # Status
        status_text, status_color = self.get_status(campaign)
        status_label = ttk.Label(
            campaign_frame, text=status_text, takefocus=False, foreground=status_color
        )
        status_label.grid(column=1, row=1, sticky="w", padx=4)
        # Starts / Ends
        MouseOverLabel(
            campaign_frame,
            text=_("gui", "inventory", "ends").format(
                time=campaign.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
            ),
            alt_text=_("gui", "inventory", "starts").format(
                time=campaign.starts_at.astimezone().replace(microsecond=0, tzinfo=None)
            ),
            reverse=campaign.upcoming,
            takefocus=False,
        ).grid(column=1, row=2, sticky="w", padx=4)
        # Linking status
        if campaign.linked:
            link_kwargs = {
                "style": '',
                "text": _("gui", "inventory", "status", "linked"),
                "foreground": "green",
            }
        else:
            link_kwargs = {
                "text": _("gui", "inventory", "status", "not_linked"),
                "foreground": "red",
            }
        LinkLabel(
            campaign_frame,
            link=campaign.link_url,
            takefocus=False,
            padding=0,
            **link_kwargs,
        ).grid(column=1, row=3, sticky="w", padx=4)
        # ACL channels
        acl = campaign.allowed_channels
        if acl:
            if len(acl) <= 5:
                allowed_text: str = '\n'.join(ch.name for ch in acl)
            else:
                allowed_text = '\n'.join(ch.name for ch in acl[:4])
                allowed_text += (
                    f"\n{_('gui', 'inventory', 'and_more').format(amount=len(acl) - 4)}"
                )
        else:
            allowed_text = _("gui", "inventory", "all_channels")
        ttk.Label(
            campaign_frame,
            text=f"{_('gui', 'inventory', 'allowed_channels')}\n{allowed_text}",
            takefocus=False,
        ).grid(column=1, row=4, sticky="nw", padx=4)
        # Image
        campaign_image = await self._cache.get(campaign.image_url, size=(108, 144))
        ttk.Label(campaign_frame, image=campaign_image).grid(column=0, row=1, rowspan=4)
        # Drops separator
        ttk.Separator(
            campaign_frame, orient="vertical", takefocus=False
        ).grid(column=2, row=0, rowspan=5, sticky="ns")
        # Drops display
        drops_row = ttk.Frame(campaign_frame)
        drops_row.grid(column=3, row=0, rowspan=5, sticky="nsew", padx=4)
        drops_row.rowconfigure(0, weight=1)
        for i, drop in enumerate(campaign.drops):
            drop_frame = ttk.Frame(drops_row, relief="ridge", borderwidth=1, padding=5)
            drop_frame.grid(column=i, row=0, padx=4)
            benefits_frame = ttk.Frame(drop_frame)
            benefits_frame.grid(column=0, row=0)
            benefit_images: list[PhotoImage] = await asyncio.gather(
                *(self._cache.get(benefit.image_url, (80, 80)) for benefit in drop.benefits)
            )
            for i, benefit, image in zip(range(len(drop.benefits)), drop.benefits, benefit_images):
                ttk.Label(
                    benefits_frame, text=benefit.name, image=image, compound="bottom"
                ).grid(column=i, row=0, padx=5)
            self._drops[drop.id] = label = MouseOverLabel(drop_frame)
            self.update_progress(drop, label)
            label.grid(column=0, row=1)
        self._campaigns[campaign] = {
            "frame": campaign_frame,
            "status": status_label,
        }
        if self._manager.tabs.current_tab() == 1:
            self._update_visibility(campaign)
            self._canvas_update()

    def clear(self) -> None:
        for child in self._main_frame.winfo_children():
            child.destroy()
        self._drops.clear()
        self._campaigns.clear()

    def get_status(self, campaign: DropsCampaign) -> tuple[str, str]:
        if campaign.active:
            status_text: str = _("gui", "inventory", "status", "active")
            status_color: str = "green"
        elif campaign.upcoming:
            status_text = _("gui", "inventory", "status", "upcoming")
            status_color = "goldenrod"
        else:
            status_text = _("gui", "inventory", "status", "expired")
            status_color = "red"
        return (status_text, status_color)

    def update_progress(self, drop: TimedDrop, label: MouseOverLabel) -> None:
        # Returns: main text, alt text, text color
        alt_text: str = ''
        progress_text: str
        reverse: bool = False
        progress_color: str = ''
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
            if datetime.now(timezone.utc) < drop.starts_at > drop.campaign.starts_at:
                # this drop can only be earned later than the campaign start
                alt_text = _("gui", "inventory", "starts").format(
                    time=drop.starts_at.astimezone().replace(microsecond=0, tzinfo=None)
                )
                reverse = True
            elif drop.ends_at < drop.campaign.ends_at:
                # this drop becomes unavailable earlier than the campaign ends
                alt_text = _("gui", "inventory", "ends").format(
                    time=drop.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
                )
                reverse = True
        label.config(
            text=progress_text, alt_text=alt_text, reverse=reverse, foreground=progress_color
        )

    def update_drop(self, drop: TimedDrop) -> None:
        label = self._drops.get(drop.id)
        if label is None:
            return
        self.update_progress(drop, label)


def proxy_validate(entry: PlaceholderEntry, settings: Settings) -> bool:
    raw_url = entry.get().strip()
    entry.replace(raw_url)
    url = URL(raw_url)
    valid = url.host is not None and url.port is not None
    if not valid:
        entry.clear()
        url = URL()
    settings.proxy = url
    return valid


class _SettingsVars(TypedDict):
    tray: IntVar
    proxy: StringVar
    dark_theme: IntVar
    autostart: IntVar
    priority_only: IntVar
    prioritze_end: IntVar
    tray_notifications: IntVar


class SettingsPanel:
    AUTOSTART_NAME: str = "TwitchDropsMiner"
    AUTOSTART_KEY: str = "HKCU/Software/Microsoft/Windows/CurrentVersion/Run"

    def __init__(self, manager: GUIManager, master: ttk.Widget, root: tk.Tk):
        self._manager = manager
        self._root = root
        self._twitch = manager._twitch
        self._settings: Settings = manager._twitch.settings
        self._vars: _SettingsVars = {
            "proxy": StringVar(master, str(self._settings.proxy)),
            "tray": IntVar(master, self._settings.autostart_tray),
            "dark_theme": IntVar(master, self._settings.dark_theme),
            "autostart": IntVar(master, self._settings.autostart),
            "priority_only": IntVar(master, self._settings.priority_only),
            "prioritze_end": IntVar(master, self._settings.prioritze_end),
            "tray_notifications": IntVar(master, self._settings.tray_notifications),
        }
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        # use a frame to center the content within the tab
        center_frame = ttk.Frame(master)
        center_frame.grid(column=0, row=0)
        # General section
        general_frame = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "settings", "general", "name")
        )
        general_frame.grid(column=0, row=0, sticky="nsew")
        # use another frame to center the options within the section
        # NOTE: this can be adjusted or removed later on if more options were to be added
        general_frame.rowconfigure(0, weight=1)
        general_frame.columnconfigure(0, weight=1)
        center_frame2 = ttk.Frame(general_frame)
        center_frame2.grid(column=0, row=0)
        # language frame
        language_frame = ttk.Frame(center_frame2)
        language_frame.grid(column=0, row=0)
        ttk.Label(language_frame, text="Language 🌐 (requires restart): ").grid(column=0, row=0)
        self._select_menu = SelectMenu(
            language_frame,
            default=_.current,
            options={k: k for k in _.languages},
            command=lambda lang: setattr(self._settings, "language", lang),
        )
        self._select_menu.grid(column=1, row=0)
        # checkboxes frame
        checkboxes_frame = ttk.Frame(center_frame2)
        checkboxes_frame.grid(column=0, row=1)
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "dark_theme")
        ).grid(column=0, row=(irow := 0), sticky="e")
        ttk.Checkbutton(
            checkboxes_frame, variable=self._vars["dark_theme"], command=self.change_theme
        ).grid(column=1, row=irow, sticky="w")
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "autostart")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        ttk.Checkbutton(
            checkboxes_frame, variable=self._vars["autostart"], command=self.update_autostart
        ).grid(column=1, row=irow, sticky="w")
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "tray")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        ttk.Checkbutton(
            checkboxes_frame, variable=self._vars["tray"], command=self.update_autostart
        ).grid(column=1, row=irow, sticky="w")
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "tray_notifications")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        ttk.Checkbutton(
            checkboxes_frame,
            variable=self._vars["tray_notifications"],
            command=self.update_notifications,
        ).grid(column=1, row=irow, sticky="w")
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "priority_only")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        ttk.Checkbutton(
            checkboxes_frame, variable=self._vars["priority_only"], command=self.priority_only
        ).grid(column=1, row=irow, sticky="w")
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "prioritze_end")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        ttk.Checkbutton(
            checkboxes_frame, variable=self._vars["prioritze_end"], command=self.prioritze_end
        ).grid(column=1, row=irow, sticky="w")
        # proxy frame
        proxy_frame = ttk.Frame(center_frame2)
        proxy_frame.grid(column=0, row=2)
        ttk.Label(proxy_frame, text=_("gui", "settings", "general", "proxy")).grid(column=0, row=0)
        self._proxy = PlaceholderEntry(
            proxy_frame,
            width=37,
            validate="focusout",
            prefill="http://",
            textvariable=self._vars["proxy"],
            placeholder="http://username:password@address:port",
        )
        self._proxy.config(validatecommand=partial(proxy_validate, self._proxy, self._settings))
        self._proxy.grid(column=0, row=1)
        # Priority section
        priority_frame = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "settings", "priority")
        )
        priority_frame.grid(column=1, row=0, sticky="nsew")
        self._priority_entry = PlaceholderCombobox(
            priority_frame, placeholder=_("gui", "settings", "game_name"), width=30
        )
        self._priority_entry.grid(column=0, row=0, sticky="ew")
        priority_frame.columnconfigure(0, weight=1)
        ttk.Button(
            priority_frame, text="+", command=self.priority_add, width=2, style="Large.TButton"
        ).grid(column=1, row=0)
        self._priority_list = PaddedListbox(
            priority_frame,
            height=10,
            padding=(1, 0),
            activestyle="none",
            selectmode="single",
            highlightthickness=0,
            exportselection=False,
        )
        self._priority_list.grid(column=0, row=1, rowspan=3, sticky="nsew")
        self._priority_list.insert("end", *self._settings.priority)
        ttk.Button(
            priority_frame,
            width=2,
            text="▲",
            style="Large.TButton",
            command=partial(self.priority_move, True),
        ).grid(column=1, row=1, sticky="ns")
        priority_frame.rowconfigure(1, weight=1)
        ttk.Button(
            priority_frame,
            width=2,
            text="▼",
            style="Large.TButton",
            command=partial(self.priority_move, False),
        ).grid(column=1, row=2, sticky="ns")
        priority_frame.rowconfigure(2, weight=1)
        ttk.Button(
            priority_frame, text="❌", command=self.priority_delete, width=2, style="Large.TButton"
        ).grid(column=1, row=3, sticky="ns")
        priority_frame.rowconfigure(3, weight=1)
        # Exclude section
        exclude_frame = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "settings", "exclude")
        )
        exclude_frame.grid(column=2, row=0, sticky="nsew")
        self._exclude_entry = PlaceholderCombobox(
            exclude_frame, placeholder=_("gui", "settings", "game_name"), width=26
        )
        self._exclude_entry.grid(column=0, row=0, sticky="ew")
        ttk.Button(
            exclude_frame, text="+", command=self.exclude_add, width=2, style="Large.TButton"
        ).grid(column=1, row=0)
        self._exclude_list = PaddedListbox(
            exclude_frame,
            height=10,
            padding=(1, 0),
            activestyle="none",
            selectmode="single",
            highlightthickness=0,
            exportselection=False,
        )
        self._exclude_list.grid(column=0, row=1, columnspan=2, sticky="nsew")
        exclude_frame.rowconfigure(1, weight=1)
        # insert them alphabetically
        self._exclude_list.insert("end", *sorted(self._settings.exclude))
        ttk.Button(
            exclude_frame, text="❌", command=self.exclude_delete, width=2, style="Large.TButton"
        ).grid(column=0, row=2, columnspan=2, sticky="ew")
        # Reload button
        reload_frame = ttk.Frame(center_frame)
        reload_frame.grid(column=0, row=1, columnspan=3, pady=4)
        ttk.Label(reload_frame, text=_("gui", "settings", "reload_text")).grid(column=0, row=0)
        ttk.Button(
            reload_frame,
            text=_("gui", "settings", "reload"),
            command=self._twitch.state_change(State.INVENTORY_FETCH),
        ).grid(column=1, row=0)

    def clear_selection(self) -> None:
        self._priority_list.selection_clear(0, "end")
        self._exclude_list.selection_clear(0, "end")

    def update_notifications(self) -> None:
        self._settings.tray_notifications = bool(self._vars["tray_notifications"].get())

    def _get_autostart_path(self, tray: bool) -> str:
        self_path = f'"{SELF_PATH.resolve()!s}"'
        if tray:
            self_path += " --tray"
        return self_path

    def change_theme(self):
        self._settings.dark_theme = bool(self._vars["dark_theme"].get())
        if self._settings.dark_theme:
            set_theme(self._root, self._manager, "dark")
        else:
            set_theme(self._root, self._manager,  "light")

    def update_autostart(self) -> None:
        enabled = bool(self._vars["autostart"].get())
        tray = bool(self._vars["tray"].get())
        self._settings.autostart = enabled
        self._settings.autostart_tray = tray
        if sys.platform == "win32":
            if enabled:
                # NOTE: we need double quotes in case the path contains spaces
                autostart_path = self._get_autostart_path(tray)
                with RegistryKey(self.AUTOSTART_KEY) as key:
                    key.set(self.AUTOSTART_NAME, ValueType.REG_SZ, autostart_path)
            else:
                with RegistryKey(self.AUTOSTART_KEY) as key:
                    key.delete(self.AUTOSTART_NAME, silent=True)
        elif sys.platform == "linux":
            autostart_folder: Path = Path("~/.config/autostart").expanduser()
            if (config_home := os.environ.get("XDG_CONFIG_HOME")) is not None:
                config_autostart: Path = Path(config_home, "autostart").expanduser()
                if config_autostart.exists():
                    autostart_folder = config_autostart
            autostart_file: Path = autostart_folder / f"{self.AUTOSTART_NAME}.desktop"
            if enabled:
                autostart_path = self._get_autostart_path(tray)
                file_contents = dedent(
                    f"""
                    [Desktop Entry]
                    Type=Application
                    Name=Twitch Drops Miner
                    Description=Mine timed drops on Twitch
                    Exec=sh -c '{autostart_path}'
                    """
                )
                with autostart_file.open("w", encoding="utf8") as file:
                    file.write(file_contents)
            else:
                autostart_file.unlink(missing_ok=True)

    def set_games(self, games: abc.Iterable[Game]) -> None:
        games_list = sorted(map(str, games))
        self._exclude_entry.config(values=games_list)
        self._priority_entry.config(values=games_list)

    def priorities(self) -> dict[str, int]:
        # NOTE: we shift the indexes so that 0 can be used as the default one
        size = self._priority_list.size()
        return {
            game_name: size - i for i, game_name in enumerate(self._priority_list.get(0, "end"))
        }

    def priority_add(self) -> None:
        game_name: str = self._priority_entry.get()
        if not game_name:
            # prevent adding empty strings
            return
        self._priority_entry.clear()
        # add it preventing duplicates
        try:
            existing_idx: int = self._settings.priority.index(game_name)
        except ValueError:
            # not there, add it
            self._priority_list.insert("end", game_name)
            self._priority_list.see("end")
            self._settings.priority.append(game_name)
            self._settings.alter()
        else:
            # already there, set the selection on it
            self._priority_list.selection_set(existing_idx)
            self._priority_list.see(existing_idx)

    def _priority_idx(self) -> int | None:
        selection: tuple[int, ...] = self._priority_list.curselection()
        if not selection:
            return None
        return selection[0]

    def priority_move(self, up: bool) -> None:
        idx: int | None = self._priority_idx()
        if idx is None:
            return
        if up and idx == 0 or not up and idx == self._priority_list.size() - 1:
            return
        swap_idx: int = idx - 1 if up else idx + 1
        item: str = self._priority_list.get(idx)
        self._priority_list.delete(idx)
        self._priority_list.insert(swap_idx, item)
        # reselect the item and scroll the list if needed
        self._priority_list.selection_set(swap_idx)
        self._priority_list.see(swap_idx)
        p = self._settings.priority
        p[idx], p[swap_idx] = p[swap_idx], p[idx]
        self._settings.alter()

    def priority_delete(self) -> None:
        idx: int | None = self._priority_idx()
        if idx is None:
            return
        self._priority_list.delete(idx)
        del self._settings.priority[idx]
        self._settings.alter()

    def priority_only(self) -> None:
        self._settings.priority_only = bool(self._vars["priority_only"].get())

    def prioritze_end(self) -> None:
        self._settings.prioritze_end = bool(self._vars["prioritze_end"].get())

    def exclude_add(self) -> None:
        game_name: str = self._exclude_entry.get()
        if not game_name:
            # prevent adding empty strings
            return
        self._exclude_entry.clear()
        exclude = self._settings.exclude
        if game_name not in exclude:
            exclude.add(game_name)
            self._settings.alter()
            # insert it alphabetically
            for i, item in enumerate(self._exclude_list.get(0, "end")):
                if game_name < item:
                    self._exclude_list.insert(i, game_name)
                    self._exclude_list.see(i)
                    break
            else:
                self._exclude_list.insert("end", game_name)
                self._exclude_list.see("end")
        else:
            # it was already there, select it
            for i, item in enumerate(self._exclude_list.get(0, "end")):
                if item == game_name:
                    existing_idx = i
                    break
            else:
                # something went horribly wrong and it's not there after all - just return
                return
            self._exclude_list.selection_set(existing_idx)
            self._exclude_list.see(existing_idx)

    def exclude_delete(self) -> None:
        selection: tuple[int, ...] = self._exclude_list.curselection()
        if not selection:
            return None
        idx: int = selection[0]
        item: str = self._exclude_list.get(idx)
        if item in self._settings.exclude:
            self._settings.exclude.discard(item)
            self._settings.alter()
            self._exclude_list.delete(idx)


class HelpTab:
    WIDTH = 800

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._twitch = manager._twitch
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        # use a frame to center the content within the tab
        center_frame = ttk.Frame(master)
        center_frame.grid(column=0, row=0)
        irow = 0
        # About
        about = ttk.LabelFrame(center_frame, padding=(4, 0, 4, 4), text="About")
        about.grid(column=0, row=(irow := irow + 1), sticky="nsew", padx=2)
        about.columnconfigure(2, weight=1)
        # About - created by
        ttk.Label(
            about, text="Application created by: ", anchor="e"
        ).grid(column=0, row=0, sticky="nsew")
        LinkLabel(
            about, link="https://github.com/DevilXD", text="DevilXD"
        ).grid(column=1, row=0, sticky="nsew")
        # About - repo link
        ttk.Label(about, text="Repository: ", anchor="e").grid(column=0, row=1, sticky="nsew")
        LinkLabel(
            about,
            link="https://github.com/DevilXD/TwitchDropsMiner",
            text="https://github.com/DevilXD/TwitchDropsMiner",
        ).grid(column=1, row=1, sticky="nsew")
        # About - donate
        ttk.Separator(
            about, orient="horizontal"
        ).grid(column=0, row=2, columnspan=3, sticky="nsew")
        ttk.Label(about, text="Donate: ", anchor="e").grid(column=0, row=3, sticky="nsew")
        LinkLabel(
            about,
            link="https://www.buymeacoffee.com/DevilXD",
            text=(
                "If you like the application and found it useful, "
                "please consider donating a small amount of money to support me. Thank you!"
            ),
            wraplength=self.WIDTH,
        ).grid(column=1, row=3, sticky="nsew")
        # Useful links
        links = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "help", "links", "name")
        )
        links.grid(column=0, row=(irow := irow + 1), sticky="nsew", padx=2)
        LinkLabel(
            links,
            link="https://www.twitch.tv/drops/inventory",
            text=_("gui", "help", "links", "inventory"),
        ).grid(column=0, row=0, sticky="nsew")
        LinkLabel(
            links,
            link="https://www.twitch.tv/drops/campaigns",
            text=_("gui", "help", "links", "campaigns"),
        ).grid(column=0, row=1, sticky="nsew")
        # How It Works
        howitworks = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "help", "how_it_works")
        )
        howitworks.grid(column=0, row=(irow := irow + 1), sticky="nsew", padx=2)
        ttk.Label(
            howitworks, text=_("gui", "help", "how_it_works_text"), wraplength=self.WIDTH
        ).grid(sticky="nsew")
        getstarted = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "help", "getting_started")
        )
        getstarted.grid(column=0, row=(irow := irow + 1), sticky="nsew", padx=2)
        ttk.Label(
            getstarted, text=_("gui", "help", "getting_started_text"), wraplength=self.WIDTH
        ).grid(sticky="nsew")


##########################################
# GUI DEFINITION END / GUI MANAGER START #
##########################################


class GUIManager:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._poll_task: asyncio.Task[NoReturn] | None = None
        self._close_requested = asyncio.Event()
        self._root = root = Tk(className=WINDOW_TITLE)
        # withdraw immediately to prevent the window from flashing
        self._root.withdraw()
        # root.resizable(False, True)
        set_root_icon(root, resource_path("pickaxe.ico"))
        root.title(WINDOW_TITLE)  # window title
        root.bind_all("<KeyPress-Escape>", self.unfocus)  # pressing ESC unfocuses selection
        # Image cache for displaying images
        self._cache = ImageCache(self)

        # style adjustments
        self._style = style = ttk.Style(root)
        default_font = nametofont("TkDefaultFont")
        # theme
        theme = ''
        # theme = style.theme_names()[6]
        # style.theme_use(theme)
        # Fix treeview's background color from tags not working (also see '_fixed_map')
        style.map(
            "Treeview",
            foreground=self._fixed_map("foreground"),
            background=self._fixed_map("background"),
        )
        # remove Notebook.focus from the Notebook.Tab layout tree to avoid an ugly dotted line
        # on tab selection. We fold the Notebook.focus children into Notebook.padding children.
        if theme != "classic":
            original = style.layout("TNotebook.Tab")
            sublayout = original[0][1]["children"][0][1]
            sublayout["children"] = sublayout["children"][0][1]["children"]
            style.layout("TNotebook.Tab", original)
        # add padding to the tab names
        style.configure("TNotebook.Tab", padding=[8, 4])
        # remove Checkbutton.focus dotted line from checkbuttons
        if theme != "classic":
            style.configure("TCheckbutton", padding=0)
            original = style.layout("TCheckbutton")
            sublayout = original[0][1]["children"]
            sublayout[1] = sublayout[1][1]["children"][0]
            del original[0][1]["children"][1]
            style.layout("TCheckbutton", original)
        # label style - green, yellow and red text
        style.configure("green.TLabel", foreground="green")
        style.configure("yellow.TLabel", foreground="goldenrod")
        style.configure("red.TLabel", foreground="red")
        # label style with a monospace font
        monospaced_font = Font(root, family="Courier New", size=10)
        style.configure("MS.TLabel", font=monospaced_font)
        # button style with a larger font
        large_font = default_font.copy()
        large_font.config(size=12)
        style.configure("Large.TButton", font=large_font)
        # label style that mimics links
        link_font = default_font.copy()
        link_font.config(underline=True)
        style.configure("Link.TLabel", font=link_font, foreground="blue")
        # end of style changes

        root_frame = ttk.Frame(root, padding=8)
        root_frame.grid(column=0, row=0, sticky="nsew")
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        # Notebook
        self.tabs = Notebook(self, root_frame)
        # Tray icon - place after notebook so it draws on top of the tabs space
        self.tray = TrayIcon(self, root_frame)
        # Main tab
        main_frame = ttk.Frame(root_frame, padding=8)
        self.tabs.add_tab(main_frame, name=_("gui", "tabs", "main"))
        self.status = StatusBar(self, main_frame)
        self.websockets = WebsocketStatus(self, main_frame)
        self.login = LoginForm(self, main_frame)
        self.progress = CampaignProgress(self, main_frame)
        self.output = ConsoleOutput(self, main_frame)
        self.channels = ChannelList(self, main_frame)
        # Inventory tab
        inv_frame = ttk.Frame(root_frame, padding=8)
        self.inv = InventoryOverview(self, inv_frame)
        self.tabs.add_tab(inv_frame, name=_("gui", "tabs", "inventory"))
        # Settings tab
        settings_frame = ttk.Frame(root_frame, padding=8)
        self.settings = SettingsPanel(self, settings_frame, root)
        self.tabs.add_tab(settings_frame, name=_("gui", "tabs", "settings"))
        # Help tab
        help_frame = ttk.Frame(root_frame, padding=8)
        self.help = HelpTab(self, help_frame)
        self.tabs.add_tab(help_frame, name=_("gui", "tabs", "help"))
        # clamp minimum window size (update geometry first)
        root.update_idletasks()
        root.minsize(width=root.winfo_reqwidth(), height=root.winfo_reqheight())
        # register logging handler
        self._handler = _TKOutputHandler(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logger = logging.getLogger("TwitchDrops")
        logger.addHandler(self._handler)
        if (logging_level := logger.getEffectiveLevel()) < logging.ERROR:
            self.print(f"Logging level: {logging.getLevelName(logging_level)}")
        # gracefully handle Windows shutdown closing the application
        if sys.platform == "win32":
            # NOTE: this root.update() is required for the below to work - don't remove
            root.update()
            self._message_map = {
                # window close request
                win32con.WM_CLOSE: self.close,
                # shutdown request
                win32con.WM_QUERYENDSESSION: self.close,
            }
            # This hooks up the wnd_proc function as the message processor for the root window.
            self.old_wnd_proc = win32gui.SetWindowLong(
                self._handle, win32con.GWL_WNDPROC, self.wnd_proc
            )
            # This ensures all of this works when the application is withdrawn or iconified
            ctypes.windll.user32.ShutdownBlockReasonCreate(
                self._handle, ctypes.c_wchar_p(_("gui", "status", "exiting"))
            )
            # DEV NOTE: use this to remove the reason in the future
            # ctypes.windll.user32.ShutdownBlockReasonDestroy(self._handle)
        else:
            # use old-style window closing protocol for non-windows platforms
            root.protocol("WM_DELETE_WINDOW", self.close)
            root.protocol("WM_DESTROY_WINDOW", self.close)
        # stay hidden in tray if needed, otherwise show the window when everything's ready
        if self._twitch.settings.tray:
            # NOTE: this starts the tray icon thread
            self._root.after_idle(self.tray.minimize)
        else:
            self._root.after_idle(self._root.deiconify)

        if self._twitch.settings.dark_theme:
            set_theme(root, self, "dark")
        else:
            set_theme(root, self, "light")

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

    def wnd_proc(self, hwnd, msg, w_param, l_param):
        """
        This function serves as a message processor for all messages sent
        to the application by Windows.
        """
        if msg == win32con.WM_DESTROY:
            win32api.SetWindowLong(self._handle, win32con.GWL_WNDPROC, self.old_wnd_proc)
        if msg in self._message_map:
            return self._message_map[msg](w_param, l_param)
        return win32gui.CallWindowProc(self.old_wnd_proc, hwnd, msg, w_param, l_param)

    @cached_property
    def _handle(self) -> int:
        return int(self._root.wm_frame(), 16)

    @property
    def running(self) -> bool:
        return self._poll_task is not None

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
        self.tray.stop()
        logging.getLogger("TwitchDrops").removeHandler(self._handler)
        self._root.destroy()

    def unfocus(self, event):
        # support pressing ESC to unfocus
        self._root.focus_set()
        self.channels.clear_selection()
        self.settings.clear_selection()

    # these are here to interface with underlaying GUI components
    def save(self, *, force: bool = False) -> None:
        self._cache.save(force=force)

    def grab_attention(self, *, sound: bool = True):
        self.tray.restore()
        self._root.focus_force()
        if sound:
            self._root.bell()

    def set_games(self, games: abc.Iterable[Game]) -> None:
        self.settings.set_games(games)

    def display_drop(
        self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False
    ) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)  # main tab
        # inventory overview is updated from within drops themselves via change events
        self.tray.update_title(drop)  # tray

    def clear_drop(self):
        self.progress.display(None)
        self.tray.update_title(None)

    def print(self, message: str):
        # print to our custom output
        self.output.print(message)


def set_theme(root, manager, name):
    style = ttk.Style(root)
    if not hasattr(set_theme, "default_style"):
        set_theme.default_style = style.theme_use()         # "Themes" is more fitting for the recolour and "Style" for the button style.

    default_font = nametofont("TkDefaultFont")
    large_font = default_font.copy()
    large_font.config(size=12)
    link_font = default_font.copy()
    link_font.config(underline=True)

    def configure_combobox_list(combobox, flag, value):
                combobox.update_idletasks()
                popdown_window = combobox.tk.call("ttk::combobox::PopdownWindow", combobox)
                listbox = f"{popdown_window}.f.l"
                combobox.tk.call(listbox, "configure", flag, value)

    # Style options, !!!"background" and "bg" is not interchangable for some reason!!!
    match name:
        case "dark":
            bg_grey = "#181818"
            active_grey = "#2b2b2b"
            # General
            style.theme_use('alt')      # We have to switch the theme, because OS-defaults ("vista") don't support certain customisations, like Treeview-fieldbackground etc.
            style.configure('.', background=bg_grey, foreground="white")
            style.configure("Link.TLabel", font=link_font, foreground="#00aaff")
            # Buttons
            style.map("TButton",
                      background=[("active", active_grey)])
            # Tabs
            style.configure("TNotebook.Tab", background=bg_grey)
            style.map("TNotebook.Tab",
                      background=[("selected", active_grey)])
            # Checkboxes
            style.configure("TCheckbutton", foreground="black") # The checkbox has to be white since it's an image, so the tick has to be black
            style.map("TCheckbutton",
                      background=[('active', active_grey)])
            # Output field
            manager.output._text.configure(bg=bg_grey, fg="white", selectbackground=active_grey)
            # Include/Exclude lists
            manager.settings._exclude_list.configure(bg=bg_grey, fg="white")
            manager.settings._priority_list.configure(bg=bg_grey, fg="white")
            # Channel list
            style.configure('Treeview', background=bg_grey, fieldbackground=bg_grey)
            manager.channels._table
            # Inventory
            manager.inv._canvas.configure(bg=bg_grey)
            # Scroll bars
            style.configure("TScrollbar", foreground="white", troughcolor=bg_grey, bordercolor=bg_grey,  arrowcolor="white")
            style.map("TScrollbar",
                      background=[("active", bg_grey), ("!active", bg_grey)])
            # Language selection box _select_menu
            manager.settings._select_menu.configure(bg=bg_grey, fg="white", activebackground=active_grey, activeforeground="white") # Couldn't figure out how to change the border, so it stays black
            for index in range(manager.settings._select_menu.menu.index("end")+1):
                 manager.settings._select_menu.menu.entryconfig(index, background=bg_grey, activebackground=active_grey, foreground="white")
            # Proxy field
            style.configure("TEntry", foreground="white", selectbackground=active_grey, fieldbackground=bg_grey)
            # Include/Exclude box
            style.configure("TCombobox", foreground="white", selectbackground=active_grey, fieldbackground=bg_grey, arrowcolor="white")
            style.map("TCombobox", background=[("active", active_grey), ("disabled", bg_grey)])
            # Include list
            configure_combobox_list(manager.settings._priority_entry, "-background", bg_grey)
            configure_combobox_list(manager.settings._priority_entry, "-foreground", "white")
            configure_combobox_list(manager.settings._priority_entry, "-selectbackground", active_grey)
            # Exclude list
            configure_combobox_list(manager.settings._exclude_entry, "-background", bg_grey)
            configure_combobox_list(manager.settings._exclude_entry, "-foreground", "white")
            configure_combobox_list(manager.settings._exclude_entry, "-selectbackground", active_grey)

        case "light" | "default" | _ : # When creating a new theme, additional values might need to be set, so the default theme remains consistent
            # General
            style.theme_use(set_theme.default_style)
            style.configure('.', background="#f0f0f0", foreground="#000000")
            # Buttons
            style.map("TButton",
                      background=[("active", "#ffffff")])
            # Tabs
            style.configure("TNotebook.Tab", background="#f0f0f0")
            style.map("TNotebook.Tab",
                      background=[("selected", "#ffffff")])
            # Checkboxes don't need to be reverted
            # Output field
            manager.output._text.configure(bg="#ffffff", fg="#000000")
            # Include/Exclude lists
            manager.settings._exclude_list.configure(bg="#ffffff", fg="#000000")
            manager.settings._priority_list.configure(bg="#ffffff", fg="#000000")
            # Channel list doesn't need to be reverted
            # Inventory
            manager.inv._canvas.configure(bg="#f0f0f0")
            # Scroll bars don't need to be reverted
            # Language selection box _select_menu
            manager.settings._select_menu.configure(bg="#ffffff", fg="black", activebackground="#f0f0f0", activeforeground="black") # Couldn't figure out how to change the border, so it stays black
            for index in range(manager.settings._select_menu.menu.index("end")+1):
                 manager.settings._select_menu.menu.entryconfig(index, background="#f0f0f0", activebackground="#0078d7", foreground="black")
            # Proxy field doesn't need to be reverted
            # Include/Exclude dropdown - Only the lists have to be reverted
            # Include list
            configure_combobox_list(manager.settings._priority_entry, "-background", "white")
            configure_combobox_list(manager.settings._priority_entry, "-foreground", "black")
            configure_combobox_list(manager.settings._priority_entry, "-selectbackground", "#0078d7")
            # Exclude list
            configure_combobox_list(manager.settings._exclude_entry, "-background", "white")
            configure_combobox_list(manager.settings._exclude_entry, "-foreground", "black")
            configure_combobox_list(manager.settings._exclude_entry, "-selectbackground", "#0078d7")


###################
# GUI MANAGER END #
###################


if __name__ == "__main__":
    # Everything below is for debug purposes only
    import aiohttp
    from types import SimpleNamespace

    class StrNamespace(SimpleNamespace):
        def __str__(self):
            if hasattr(self, "_str__"):
                return self._str__(self)
            return super().__str__()

    class HashNamespace(SimpleNamespace):
        __hash__ = object.__hash__  # type: ignore

    def create_game(id: int, name: str):
        return StrNamespace(name=name, id=id, _str__=lambda s: s.name)

    iid = 0

    def create_channel(
        name: str,
        status: int,
        game: str | None,
        drops: bool,
        viewers: int,
        points: int,
        acl_based: bool,
    ):
        # status: 0 -> OFFLINE, 1 -> PENDING_ONLINE, 2 -> ONLINE
        if status == 1:
            status = False
            pending = True
        else:
            pending = False
        if game is not None:
            game_obj: StrNamespace | None = create_game(0, game)
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
            acl_based=acl_based,
        )

    def create_drop(
        campaign_name: str,
        game_name: str,
        rewards: list[str],
        claimed_drops: int,
        total_drops: int,
        current_minutes: int,
        total_minutes: int,
    ):
        cd = claimed_drops
        td = total_drops
        cm = current_minutes
        tm = total_minutes
        ref_stamp = datetime.now(timezone.utc).replace(minute=0, second=0)
        image_url = (
            "https://static-cdn.jtvnw.net/twitch-drops-assets-prod/"
            "BENEFIT-81ab5665-b2f4-4179-96e6-74da5a82da28.jpeg"
        )
        benefits = [SimpleNamespace(name=name, image_url=image_url) for name in rewards]
        mock = SimpleNamespace(
            id="0",
            campaign=HashNamespace(
                name=campaign_name,
                id="campaign",
                game=create_game(0, game_name),
                expired=False,
                active=False,
                upcoming=True,
                linked=False,
                finished=False,
                link_url="https://google.com",
                image_url="https://static-cdn.jtvnw.net/ttv-boxart/460630-285x380.jpg",
                allowed_channels=[],
                starts_at=ref_stamp,
                ends_at=ref_stamp + timedelta(days=7),
                timed_drops={},
                claimed_drops=cd,
                total_drops=td,
                remaining_drops=td - cd,
                progress=(cd * tm + cm) / (td * tm),
                remaining_minutes=(td - cd) * tm - cm,
            ),
            image_url=image_url,
            can_claim=False,
            can_earn=lambda: False,
            is_claimed=False,
            preconditions=True,
            benefits=benefits,
            rewards_text=lambda: ', '.join(b.name for b in benefits),
            progress=cm/tm,
            current_minutes=cm,
            required_minutes=tm,
            remaining_minutes=tm-cm,
        )
        mock.campaign.timed_drops["0"] = mock
        mock.campaign.drops = mock.campaign.timed_drops.values()
        return mock

    async def main(exit_event: asyncio.Event):
        # Initialize GUI debug
        mock = SimpleNamespace(
            settings=SimpleNamespace(
                tray=False,
                priority=[],
                proxy=URL(),
                dark_theme=False,
                autostart=False,
                language="English",
                priority_only=False,
                prioritze_end=False,
                autostart_tray=False,
                exclude={"Lit Game"},
                tray_notifications=True
            )
        )
        mock.change_state = lambda state: mock.gui.print(f"State change: {state.value}")
        mock.state_change = lambda state: partial(mock.change_state, state)
        mock.request = aiohttp.request
        gui = GUIManager(mock)  # type: ignore
        mock.gui = gui
        mock.close = gui.stop
        gui.start()
        assert gui._poll_task is not None
        gui._poll_task.add_done_callback(lambda t: exit_event.set())
        # Login form
        gui.login.update("Login required", None)
        # Game selector and settings panel games
        gui.set_games([
            create_game(420690, "Lit Game"),
            create_game(123456, "Best Game"),
            create_game(654321, "My Game Very Long Name"),
        ])
        # Channel list
        gui.channels.display(
            create_channel(
                name="Thomus",
                status=0,
                game=None,
                drops=False,
                viewers=0,
                points=0,
                acl_based=True,
            ),
            add=True,
        )
        channel = create_channel(
            name="Traitus", status=1, game=None, drops=False, viewers=0, points=0, acl_based=True
        )
        gui.channels.display(channel, add=True,)
        gui.channels.set_watching(channel)
        gui.channels.display(
            create_channel(
                name="Testus",
                status=2,
                game="Best Game",
                drops=True,
                viewers=42,
                points=1234567,
                acl_based=False,
            ),
            add=True,
        )
        gui.channels.display(
            create_channel(
                name="Livus",
                status=2,
                game="Best Game",
                drops=True,
                viewers=69,
                points=1234567,
                acl_based=False,
            ),
            add=True,
        )
        gui._root.update()
        gui.channels.get_selection()
        # Inventory overview
        drop = create_drop(
            "Wardrobe Cleaning", "Cleaning Masters", ["Fancy Pants"], 2, 7, 239, 240
        )
        campaign = drop.campaign
        await gui.inv.add_campaign(campaign)

        gui.print("Single-line test message")
        await asyncio.sleep(1)
        gui.print("Multi-line\ntest\nmessage")

        # Tray
        # gui.tray.minimize()
        await asyncio.sleep(2)
        claim_text = (
            f"{campaign.game.name}\n"
            f"{drop.rewards_text()} ({campaign.claimed_drops}/{campaign.total_drops})"
        )
        gui.tray.notify(claim_text, "Mined Drop")

        # Drop progress
        gui.display_drop(drop, countdown=False)
        await asyncio.sleep(3)
        gui.progress.start_timer()
        await asyncio.sleep(5)
        gui.clear_drop()
        await asyncio.sleep(5)
        gui.display_drop(drop)

        await asyncio.sleep(63)
        drop.current_minutes = 240
        drop.remaining_minutes = 0
        drop.progress = 1.0
        campaign = drop.campaign
        campaign.remaining_minutes -= 1
        campaign.progress = 3/7
        campaign.claimed_drops = 3
        campaign.remaining_drops = 4
        gui.display_drop(drop)
        await asyncio.sleep(10)
        drop.current_minutes = 0
        drop.remaining_minutes = 240
        drop.progress = 0.0
        gui.display_drop(drop)

    def main_exit(task: asyncio.Task[None]) -> None:
        if task.exception() is not None:
            exit_event.set()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    exit_event = asyncio.Event()
    main_task = loop.create_task(main(exit_event))
    main_task.add_done_callback(main_exit)
    loop.run_until_complete(exit_event.wait())
    if main_task.done():
        loop.run_until_complete(main_task)
