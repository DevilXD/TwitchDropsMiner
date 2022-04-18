from __future__ import annotations

import asyncio
import logging
import tkinter as tk
from math import log10, ceil
from functools import partial
from tkinter.font import Font
from collections import abc, namedtuple
from tkinter import Tk, ttk, StringVar, DoubleVar, IntVar
from typing import Any, TypedDict, NoReturn, TYPE_CHECKING

import pystray
from yarl import URL
from PIL import Image as Image_module

from cache import ImageCache
from exceptions import ExitRequest
from utils import resource_path, Game
from registry import RegistryKey, ValueType
from constants import SELF_PATH, FORMATTER, WS_TOPICS_LIMIT, MAX_WEBSOCKETS, WINDOW_TITLE, State

if TYPE_CHECKING:
    from twitch import Twitch
    from channel import Channel
    from settings import Settings
    from inventory import DropsCampaign, TimedDrop


digits = ceil(log10(WS_TOPICS_LIMIT))
WS_FONT = ("Courier New", 10)
LARGE_FONT = (..., 12)


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
    def __init__(self, master: ttk.Widget, *args, padding: tk._Padding = (0, 0, 0, 0), **kwargs):
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
        options = {}
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
            padding: tk._Padding = options.pop("padding")
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
                pady1 = pady2 = padding[1]  # type: ignore
            elif len(padding) == 3:
                padx1, padx2 = padding[0:2]  # type: ignore
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
    def __init__(self, *args, alt_text: str = '', **kwargs) -> None:
        options = {}
        if args and args[0] is not None:
            options.update(args[0])
        if kwargs:
            options.update(kwargs)
        self._org_text: str = options.get("text", '')
        self._alt_text: str = alt_text
        super().__init__(*args, **kwargs)
        self.bind("<Enter>", lambda e: self.config(text=self._alt_text))
        self.bind("<Leave>", lambda e: self.config(text=self._org_text))


class _WSEntry(TypedDict):
    status: str
    topics: int


class WebsocketStatus:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._status_var = StringVar(master)
        self._topics_var = StringVar(master)
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
        self._items: dict[int, _WSEntry | None] = {i: None for i in range(MAX_WEBSOCKETS)}
        self._update()

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
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
        status_lines: list[str] = []
        topic_lines: list[str] = []
        for idx in range(MAX_WEBSOCKETS):
            if (item := self._items.get(idx)) is None:
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
        self._var = StringVar(master)
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
        # NOTE: we need this to allow for the closing window event to break the waiting here
        await asyncio.wait(
            [self._confirm.wait(), self._manager.wait_until_closed()],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if self._manager.close_requested:
            raise ExitRequest()
        self._button.config(state="disabled")
        data = LoginData(self._login_entry.get(), self._pass_entry.get(), self._token_entry.get())
        return data

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
                "name": StringVar(master, "..."),  # campaign name
                "progress": DoubleVar(master),  # controls the progress bar
                "percentage": StringVar(master, "-%"),  # percentage display string
                "remaining": StringVar(master),  # time remaining string, filled via _update_time
            },
            "drop": {
                "rewards": StringVar(master, "..."),  # drop rewards
                "progress": DoubleVar(master),  # as above
                "percentage": StringVar(master, "-%"),  # as above
                "remaining": StringVar(master),  # as above
            },
        }
        self._frame = frame = ttk.LabelFrame(
            master, text="Campaign Progress", padding=(4, 0, 4, 4)
        )
        frame.grid(column=0, row=1, columnspan=2, sticky="nsew", padx=2)
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
        self._drop: TimedDrop | None = None
        self._timer_task: asyncio.Task[None] | None = None
        self._update_time(0)

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


class _Buttons(TypedDict):
    frame: ttk.Frame
    switch: ttk.Button
    load_points: ttk.Button


class ChannelList:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        frame = ttk.LabelFrame(master, text="Channels", padding=(4, 0, 4, 4))
        frame.grid(column=2, row=0, rowspan=3, sticky="nsew", padx=2)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        # tell master frame that the containing column can expand
        master.columnconfigure(2, weight=1)
        buttons_frame = ttk.Frame(frame)
        self._buttons: _Buttons = {
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
        self._const_width: set[str] = set()
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
        self._channel_map: dict[str, Channel] = {}

    def _add_column(
        self,
        cid: str,
        name: str,
        *,
        anchor: tk._Anchor = "center",
        width: int | None = None,
        width_template: str | None = None,
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
        self.icon: pystray.Icon | None = None
        self._button = ttk.Button(master, command=self.minimize, text="Minimize to Tray")
        self._button.grid(column=0, row=0, sticky="ne")

    def is_tray(self) -> bool:
        return self.icon is not None

    def get_title(self, drop: TimedDrop | None) -> str:
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
                Image_module.open(resource_path("pickaxe.ico")),
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

    def notify(
        self, message: str, title: str | None = None, duration: float = 10
    ) -> asyncio.Task[None] | None:
        if self.icon is not None:
            icon = self.icon

            async def notifier():
                icon.notify(message, title)
                await asyncio.sleep(duration)
                icon.remove_notification()

            return asyncio.create_task(notifier())
        return None

    def update_title(self, drop: TimedDrop):
        if self.icon is not None:
            self.icon.title = self.get_title(drop)


class Notebook:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._nb = ttk.Notebook(master)
        self._nb.grid(column=0, row=0, sticky="nsew")
        # prevent entries from being selected after switching tabs
        self._nb.bind("<<NotebookTabChanged>>", lambda event: manager._root.focus_set())
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)

    def add_tab(self, widget: ttk.Widget, *, name: str, **kwargs):
        kwargs.pop("text", None)
        if "sticky" not in kwargs:
            kwargs["sticky"] = "nsew"
        self._nb.add(widget, text=name, **kwargs)


class InventoryOverview:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._cache = manager._cache
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        self._canvas = tk.Canvas(master, scrollregion=(0, 0, 0, 0))
        self._canvas.grid(column=0, row=0, sticky="nsew")
        xscroll = ttk.Scrollbar(master, orient="horizontal", command=self._canvas.xview)
        xscroll.grid(column=0, row=1, sticky="ew")
        yscroll = ttk.Scrollbar(master, orient="vertical", command=self._canvas.yview)
        yscroll.grid(column=1, row=0, sticky="ns")
        self._canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self._canvas.bind("<Configure>", self._canvas_update)
        self._main_frame = ttk.Frame(self._canvas)
        self._canvas.bind(
            "<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        )
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))
        self._canvas.create_window(0, 0, anchor="nw", window=self._main_frame)
        self._campaigns: list[DropsCampaign] = []
        self._drops: dict[str, ttk.Label] = {}

    def _canvas_update(self, event: tk.Event[tk.Canvas]):
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
        self._campaigns.append(campaign)
        campaign_frame.rowconfigure(3, weight=1)
        campaign_frame.columnconfigure(1, weight=1)
        campaign_frame.columnconfigure(3, weight=10000)
        ttk.Label(
            campaign_frame, text=campaign.name, takefocus=False, width=45
        ).grid(column=0, row=0, columnspan=2, sticky="w")
        if campaign.active:
            status_text: str = "Active ✔"
            status_color: tk._Color = "green"
        elif campaign.upcoming:
            status_text = "Upcoming ⏳"
            status_color = "goldenrod"
        else:
            status_text = "Expired ❌"
            status_color = "red"
        ttk.Label(
            campaign_frame, text=status_text, takefocus=False, foreground=status_color
        ).grid(column=1, row=1, sticky="w", padx=4)
        MouseOverLabel(
            campaign_frame,
            text=f"Ends: {campaign.ends_at.astimezone().replace(microsecond=0, tzinfo=None)}",
            alt_text=(
                f"Starts: {campaign.starts_at.astimezone().replace(microsecond=0, tzinfo=None)}"
            ),
            takefocus=False,
        ).grid(column=1, row=2, sticky="w", padx=4)
        acl = campaign.allowed_channels
        if acl:
            if len(acl) <= 5:
                allowed_text: str = '\n'.join(ch.name for ch in acl)
            else:
                allowed_text = '\n'.join(ch.name for ch in acl[:4])
                allowed_text += f"\nand {len(acl) - 4} more..."
        else:
            allowed_text = "All"
        ttk.Label(
            campaign_frame, text=f"Allowed channels:\n{allowed_text}", takefocus=False
        ).grid(column=1, row=3, sticky="nw", padx=4)
        campaign_image = await self._cache.get(campaign.image_url, size=(96, 128))
        ttk.Label(campaign_frame, image=campaign_image).grid(column=0, row=1, rowspan=3)
        ttk.Separator(
            campaign_frame, orient="vertical", takefocus=False
        ).grid(column=2, row=0, rowspan=4, sticky="ns")
        drops_row = ttk.Frame(campaign_frame)
        drops_row.grid(column=3, row=0, rowspan=4, sticky="nsew", padx=4)
        drops_row.rowconfigure(0, weight=1)
        for i, drop in enumerate(campaign.drops):
            drop_frame = ttk.Frame(drops_row, relief="ridge", borderwidth=1, padding=5)
            drop_frame.grid(column=i, row=0, padx=4)
            drop_image = await self._cache.get(drop.image_url, (80, 80))
            ttk.Label(
                drop_frame, text=drop.rewards_text(), image=drop_image, compound="bottom"
            ).grid(column=0, row=0)
            progress_text, progress_color = self.get_progress(drop)
            self._drops[drop.id] = label = ttk.Label(
                drop_frame, text=progress_text, foreground=progress_color
            )
            label.grid(column=0, row=1)

    def clear(self) -> None:
        for child in self._main_frame.winfo_children():
            child.destroy()
        self._campaigns.clear()

    def get_progress(self, drop: TimedDrop) -> tuple[str, tk._Color]:
        progress_text: str = ''
        progress_color: tk._Color = ''
        if drop.is_claimed:
            progress_text = "Claimed ✔"
            progress_color = "green"
        elif drop.can_claim:
            progress_text = "Ready to claim ⏳"
            progress_color = "goldenrod"
        elif drop.preconditions:
            progress_text = f"{drop.progress:3.1%} of {drop.required_minutes} minutes"
        return (progress_text, progress_color)

    def update_drop(self, drop: TimedDrop) -> None:
        label = self._drops.get(drop.id)
        if label is None:
            return
        progress_text, progress_color = self.get_progress(drop)
        label.config(text=progress_text, foreground=progress_color)


def proxy_validate(entry: PlaceholderEntry, settings: Settings) -> bool:
    raw_url = entry.get().strip()
    entry.replace(raw_url)
    url = URL(raw_url)
    valid = url.host is not None and url.port is not None
    if valid:
        settings.proxy = url
    else:
        entry.delete(0, "end")
    return valid


class _SettingsVars(TypedDict):
    tray: IntVar
    proxy: StringVar
    autostart: IntVar
    priority_only: IntVar


class SettingsPanel:
    AUTOSTART_NAME: str = "TwitchDropsMiner"

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._twitch = manager._twitch
        self._settings: Settings = manager._twitch.settings
        self._vars: _SettingsVars = {
            "proxy": StringVar(master, str(self._settings.proxy)),
            "tray": IntVar(master, self._settings.autostart_tray),
            "autostart": IntVar(master, self._settings.autostart),
            "priority_only": IntVar(master, self._settings.priority_only),
        }
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        # use a frame to center the content within the tab
        center_frame = ttk.Frame(master)
        center_frame.grid(column=0, row=0)
        # General section
        general_frame = ttk.LabelFrame(center_frame, padding=(4, 0, 4, 4), text="General")
        general_frame.grid(column=0, row=0, sticky="nsew")
        # use another frame to center the options within the section
        # NOTE: this can be adjusted or removed later on if more options were to be added
        general_frame.rowconfigure(0, weight=1)
        general_frame.columnconfigure(0, weight=1)
        center_frame2 = ttk.Frame(general_frame)
        center_frame2.grid(column=0, row=0)
        ttk.Label(center_frame2, text="Autostart: ").grid(column=0, row=0, sticky="e")
        ttk.Checkbutton(
            center_frame2, variable=self._vars["autostart"], command=self.update_autostart
        ).grid(column=1, row=0, sticky="w")
        ttk.Label(center_frame2, text="Autostart into tray: ").grid(column=0, row=1, sticky="e")
        ttk.Checkbutton(
            center_frame2, variable=self._vars["tray"], command=self.update_autostart
        ).grid(column=1, row=1, sticky="w")
        ttk.Label(center_frame2, text="Priority only: ").grid(column=0, row=2, sticky="e")
        ttk.Checkbutton(
            center_frame2, variable=self._vars["priority_only"], command=self.priority_only
        ).grid(column=1, row=2, sticky="w")
        ttk.Label(
            center_frame2, text="Proxy (requires restart):"
        ).grid(column=0, row=3, columnspan=2)
        self._proxy = PlaceholderEntry(
            center_frame2,
            width=37,
            validate="focusout",
            prefill="http://",
            textvariable=self._vars["proxy"],
            placeholder="http://username:password@address:port",
        )
        self._proxy.config(validatecommand=partial(proxy_validate, self._proxy, self._settings))
        self._proxy.grid(column=0, row=4, columnspan=2)
        # Priority section
        priority_frame = ttk.LabelFrame(center_frame, padding=(4, 0, 4, 4), text="Priority")
        priority_frame.grid(column=1, row=0, sticky="nsew")
        self._priority_entry = PlaceholderCombobox(
            priority_frame, placeholder="Game name", width=30
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
        exclude_frame = ttk.LabelFrame(center_frame, padding=(4, 0, 4, 4), text="Exclude")
        exclude_frame.grid(column=2, row=0, sticky="nsew")
        self._exclude_entry = PlaceholderCombobox(exclude_frame, placeholder="Game name", width=26)
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
        ttk.Label(
            reload_frame,
            text="Most changes require a reload to take an immediate effect: "
        ).grid(column=0, row=0)
        ttk.Button(
            reload_frame, text="Reload", command=self._twitch.state_change(State.INVENTORY_FETCH)
        ).grid(column=1, row=0)

    def clear_selection(self) -> None:
        self._priority_list.selection_clear(0, "end")
        self._exclude_list.selection_clear(0, "end")

    def update_autostart(self) -> None:
        enabled = bool(self._vars["autostart"].get())
        tray = bool(self._vars["tray"].get())
        self._settings.autostart = enabled
        self._settings.autostart_tray = tray
        if enabled:
            # NOTE: we need double quotes in case the path contains spaces
            self_path = f'"{SELF_PATH.resolve()!s}"'
            if tray:
                self_path += " --tray"
            with RegistryKey("HKCU/Software/Microsoft/Windows/CurrentVersion/Run") as key:
                key.set(self.AUTOSTART_NAME, ValueType.REG_SZ, self_path)
        else:
            with RegistryKey("HKCU/Software/Microsoft/Windows/CurrentVersion/Run") as key:
                key.delete(self.AUTOSTART_NAME, silent=True)

    def set_games(self, games: abc.Iterable[Game]) -> None:
        games_list = sorted(map(str, games))
        self._exclude_entry.config(values=games_list)
        self._priority_entry.config(values=games_list)

    def priorities(self) -> dict[str, int]:
        # NOTE: we shift the indexes so that 0 can be used as the default one
        size = self._priority_list.size()
        return {
            game_name: i - size for i, game_name in enumerate(self._priority_list.get(0, "end"))
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

    def priority_delete(self) -> None:
        idx: int | None = self._priority_idx()
        if idx is None:
            return
        self._priority_list.delete(idx)
        del self._settings.priority[idx]

    def priority_only(self) -> None:
        self._settings.priority_only = bool(self._vars["priority_only"].get())

    def exclude_add(self) -> None:
        game_name: str = self._exclude_entry.get()
        if not game_name:
            # prevent adding empty strings
            return
        self._exclude_entry.clear()
        exclude = self._settings.exclude
        if game_name not in exclude:
            exclude.add(game_name)
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
            self._exclude_list.delete(idx)


class GUIManager:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._poll_task: asyncio.Task[NoReturn] | None = None
        self._closed = asyncio.Event()
        self._root = root = Tk()
        # withdraw immediately to prevent the window from flashing
        self._root.withdraw()
        # root.resizable(False, True)
        root.iconbitmap(resource_path("pickaxe.ico"))  # window icon
        root.title(WINDOW_TITLE)  # window title
        root.protocol("WM_DELETE_WINDOW", self.close)  # hook the X window closing button
        root.bind_all("<KeyPress-Escape>", self.unfocus)  # pressing ESC unfocuses selection
        # Image cache for displaying images
        self._cache = ImageCache(self)

        # style adjustements
        self._style = style = ttk.Style(root)
        # theme
        theme = ''
        # theme = style.theme_names()[6]
        # style.theme_use(theme)
        # fix treeview's background color from tags not working (also see '_fixed_map')
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
        # adds a style with a larger font for buttons
        style.configure("Large.TButton", font=LARGE_FONT)
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
        self.tabs.add_tab(main_frame, name="Main")
        self.websockets = WebsocketStatus(self, main_frame)
        self.login = LoginForm(self, main_frame)
        self.progress = CampaignProgress(self, main_frame)
        self.output = ConsoleOutput(self, main_frame)
        self.channels = ChannelList(self, main_frame)
        # Inventory tab
        inv_frame = ttk.Frame(root_frame, padding=8)
        self.inv = InventoryOverview(self, inv_frame)
        self.tabs.add_tab(inv_frame, name="Inventory")
        # Settings tab
        settings_frame = ttk.Frame(root_frame, padding=8)
        self.settings = SettingsPanel(self, settings_frame)
        self.tabs.add_tab(settings_frame, name="Settings")
        # clamp minimum window size (update geometry first)
        root.update_idletasks()
        root.minsize(width=root.winfo_reqwidth(), height=root.winfo_reqheight())
        # register logging handler
        self._handler = _TKOutputHandler(self)
        self._handler.setFormatter(FORMATTER)
        logging.getLogger("TwitchDrops").addHandler(self._handler)
        # stay hidden in tray if needed, otherwise show the window when everything's ready
        if self._twitch.settings.tray:
            # NOTE: this starts the tray icon thread
            self._root.after_idle(self.tray.minimize)
        else:
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

    async def wait_until_closed(self):
        # wait until the user closes the window
        await self._closed.wait()

    def prevent_close(self):
        self._closed.clear()

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
        self.settings.clear_selection()

    # these are here to interface with underlaying GUI components
    def save(self) -> None:
        self._cache.save()

    def set_games(self, games: abc.Iterable[Game]) -> None:
        self.settings.set_games(games)

    def display_drop(
        self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False
    ) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)  # main tab
        self.inv.update_drop(drop)  # inventory
        self.tray.update_title(drop)  # tray

    def print(self, *args, **kwargs):
        # print to our custom output
        self.output.print(*args, **kwargs)


if __name__ == "__main__":
    # Everything below is for debug purposes only
    from types import SimpleNamespace
    from datetime import datetime, timedelta, timezone

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
        game: str | None,
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
        ref_stamp = datetime.now(timezone.utc).replace(minute=0, second=0)
        mock = SimpleNamespace(
            id="0",
            campaign=SimpleNamespace(
                name=campaign_name,
                id="campaign",
                active=False,
                upcoming=True,
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
            image_url=(
                "https://static-cdn.jtvnw.net/twitch-drops-assets-prod/"
                "BENEFIT-81ab5665-b2f4-4179-96e6-74da5a82da28.jpeg"
            ),
            can_claim=False,
            is_claimed=False,
            preconditions=True,
            rewards_text=lambda: rewards,
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
                autostart=False,
                priority_only=False,
                autostart_tray=False,
                exclude={"Lit Game"},
            )
        )
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
        # Game selector and settings panel games
        gui.set_games([
            create_game(420690, "Lit Game"),
            create_game(123456, "Best Game"),
            create_game(654321, "My Game Very Long Name"),
        ])
        # Channel list
        gui.channels.display(
            create_channel(
                name="Thomus", status=0, game=None, drops=False, viewers=0, points=0, priority=True
            ),
            add=True,
        )
        channel = create_channel(
            name="Traitus", status=1, game=None, drops=False, viewers=0, points=0, priority=True
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
                priority=False,
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
                priority=False,
            ),
            add=True,
        )
        gui._root.update()
        gui.channels.get_selection()
        # Tray
        # gui.tray.minimize()
        await asyncio.sleep(1)
        gui.tray.notify("Bounty Coins (3/7)", "Mined Drop")
        # Inventory overview
        drop = create_drop("Wardrobe Cleaning", "Fancy Pants", 2, 7, 239, 240)
        await gui.inv.add_campaign(drop.campaign)
        # Drop progress
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

    loop = asyncio.get_event_loop()
    exit_event = asyncio.Event()
    main_task = loop.create_task(main(exit_event))
    main_task.add_done_callback(main_exit)
    loop.run_until_complete(exit_event.wait())
    if main_task.done():
        loop.run_until_complete(main_task)
