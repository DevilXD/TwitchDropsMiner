# WebUIManager — NiceGUI-based drop-in replacement for the tkinter GUIManager.
#
# Architecture overview
# ---------------------
# The application core (twitch.py) is written against a "GUIManager" interface
# that was originally implemented with tkinter widgets. WebUIManager reimplements
# that same interface so that twitch.py never needs to know whether it is talking
# to a desktop window or a browser tab.
#
# The interface is satisfied in two layers:
#
#   1. *Adapter objects (see adapters/*.py) – one per tkinter widget class
#      (StatusBar, ChannelList, LoginForm, …). They are stored as attributes on
#      WebUIManager (self.status, self.channels, self.login, …) so that every
#      call site in twitch.py keeps working unchanged.
#
#   2. WebUIManager itself – owns the NiceGUI server, the shared UI state, and all
#      top-level methods (print, close, display_drop, …) that twitch.py calls
#      directly on the manager object.
#
# Single-threaded architecture
# ----------------------------
# Since the backend now runs within NiceGUI's event loop, everything operates on
# the same asyncio loop. This eliminates the need for thread synchronization.
# UI updates can be made directly since we're always on the NiceGUI loop.
#
# Late-joining clients
# --------------------
# Multiple browser tabs can connect at any time, even after the miner has been
# running for a while. Mutable UI state is persisted on each panel object, with
# a small amount of global state (status text, console log) on the manager, so
# that a fresh page load can show up to date information.

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from nicegui import ui, Client, app

from constants import OUTPUT_FORMATTER, FILE_FORMATTER
from .adapters import (
    TrayIconAdapter,
    StatusBarAdapter,
    CampaignProgressAdapter,
    ConsoleOutputAdapter,
    ChannelListAdapter,
    InventoryOverviewAdapter,
    LoginFormAdapter,
    WebsocketStatusAdapter,
    SettingsAdapter,
    TabsAdapter,
)
from .handlers import WebUIOutputHandler
from .html_utils import favicon_js
from .components import (
    BasePanel,
    MainPanel,
    InventoryPanel,
    HelpPanel,
    SettingsPanel,
    HeaderBar,
)

if TYPE_CHECKING:
    from twitch import Twitch
    from utils import Game


class WebUIManager:
    """
    NiceGUI-based web interface that is a drop-in replacement for the tkinter GUIManager.

    WebUIManager owns:
    - The NiceGUI HTTP server (started in a daemon thread by _start_server).
    - All shared mutable UI state (status text, console log, channel map, …)
      that the *Adapter attribute objects write to and the NiceGUI timer reads from.
    - The top-level methods (print, close, display_drop, …) called directly by
      twitch.py on the manager object.

    The *Adapter objects stored as attributes mirror the tkinter widget classes that
    twitch.py expects (self.status → StatusBar, self.channels → ChannelList, …).
    See adapters/*.py for details.
    """

    def __init__(self, twitch: "Twitch"):
        self._twitch: "Twitch" = twitch
        self._close_requested = asyncio.Event()
        self._running = False

        # Shared UI state
        self._current_icon: str = "pickaxe"
        self._dark_mode_enabled: bool = twitch.settings.dark_mode
        self._status_text: str = "Initializing..."
        self._console_log: list[str] = []

        # Adapters - mirrors of classes in gui.py
        self.tray = TrayIconAdapter(self)
        self.status = StatusBarAdapter(self)
        self.progress = CampaignProgressAdapter(self)
        self.output = ConsoleOutputAdapter(self)
        self.channels = ChannelListAdapter(self)
        self.inv = InventoryOverviewAdapter(self)
        self.login = LoginFormAdapter(self)
        self.websockets = WebsocketStatusAdapter(self)
        self.settings = SettingsAdapter(self)
        self.tabs = TabsAdapter()

        # Panel objects - own all widget references and state for their tab
        self.header_bar: HeaderBar = HeaderBar(self)
        self.main_panel: MainPanel = MainPanel(self)
        self.inventory_panel: BasePanel = InventoryPanel(self)
        self.settings_panel: BasePanel = SettingsPanel(self)
        self.help_panel: BasePanel = HelpPanel(self)

        self._setup_ui()

        # Use the same log formatter as gui.py's _TKOutputHandler so messages look identical.
        self._handler = WebUIOutputHandler(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logger = logging.getLogger("TwitchDrops")
        logger.addHandler(self._handler)
        if (logging_level := logger.getEffectiveLevel()) < logging.ERROR:
            self.print(f"Logging level: {logging.getLevelName(logging_level)}")

    def _setup_ui(self):
        """Register the NiceGUI page handler. The inner index() function runs once
        per browser connection, building the full UI for that client."""
        app.add_static_files("/icons", str(Path(__file__).parent.parent / "icons"))
        _css = (Path(__file__).parent / "styles.css").read_text(encoding="utf-8")

        @ui.page("/")
        def index(tab: str = "main"):
            ui.page_title("Twitch Drops Miner")
            ui.dark_mode(self._dark_mode_enabled)
            ui.query(".nicegui-content").classes("p-0")
            ui.add_head_html(f"<style>{_css}</style>")

            # Fixed header + scrollable content below it only.
            # .q-page-container starts at y=0 (behind the fixed header) with
            # Quasar-injected padding-top equal to the header height. Putting
            # overflow-y-auto on it makes the scrollbar run from y=0 (behind the
            # header) downward. Moving scroll to .q-page fixes this: .q-page
            # begins after the padding, so its scrollbar starts below the header.
            ui.query("html").classes("!overflow-hidden !h-screen")
            ui.query("body").classes("!overflow-hidden !h-screen")
            ui.query(".q-page-container").classes(
                "!box-border !h-screen !overflow-hidden"
            )
            ui.query(".q-page").classes("!h-full !min-h-0 !overflow-y-auto")

            # Set favicon to current icon state for late-joining clients
            ui.run_javascript(favicon_js(self._current_icon))

            # Request notification permission on page load
            ui.run_javascript(
                """
                if ('Notification' in window && Notification.permission === 'default') {
                    Notification.requestPermission();
                }
            """
            )

            # Alias so nested closures below can reference the manager unambiguously.
            manager = self

            # Fall back to 'main' if the ?tab= query param is not a known tab name.
            initial_tab = (
                tab if tab in ("main", "inventory", "settings", "help") else "main"
            )

            def _on_tab_change(e):
                t = str(e.value)
                ui.run_javascript(f"history.replaceState(null, '', '?tab={t}')")

            tabs = manager.header_bar.build(initial_tab, _on_tab_change)

            with ui.tab_panels(tabs, value=initial_tab).classes("w-full h-full"):
                with ui.tab_panel("main"):
                    manager.main_panel.build()

                with ui.tab_panel("inventory"):
                    manager.inventory_panel.build()

                with ui.tab_panel("settings"):
                    manager.settings_panel.build()

                with ui.tab_panel("help"):
                    manager.help_panel.build()

    def set_dark_mode(self, enabled: bool) -> None:
        """Apply dark mode to all connected clients."""
        self._dark_mode_enabled = enabled
        self._twitch.settings.dark_mode = enabled
        self._twitch.settings.save()

        async def _apply(client) -> None:
            with client:
                ui.dark_mode(enabled)

        for client in list(Client.instances.values()):
            asyncio.get_event_loop().create_task(_apply(client))

    @property
    def running(self) -> bool:
        return self._running

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    def print(self, message: str):
        """Append a timestamped line to the in-browser console log.
        Matches gui.py ConsoleOutput.print(): each line of a multiline message gets its own stamp.
        """
        stamp = datetime.now().strftime("%X")
        if "\n" in message:
            display_message = message.replace("\n", f"\n{stamp}: ")
        else:
            display_message = message

        lines = [f"{stamp}: {line}" for line in display_message.split("\n")]
        # Persist every line so late-joining clients can replay the full log on connect.
        self._console_log.extend(lines)

        # Direct call since we're on the same event loop now
        self.main_panel.push_console(lines)

        # Mirror to stdout/file when stdlog is enabled, matching gui.py behaviour.
        if self._twitch.settings.stdlog:
            record = logging.LogRecord(
                name="GUI",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None,
            )
            print(FILE_FORMATTER.format(record))

    def close(self, *args) -> int:
        """Signal the main loop to shut down (mirrors GUIManager.close)."""
        self._close_requested.set()
        return 0

    async def wait_until_closed(self):
        """Wait until the user closes the window"""
        await self._close_requested.wait()

    def stop(self):
        self._running = False

    def close_window(self):
        logging.getLogger("TwitchDrops").removeHandler(self._handler)
        app.shutdown()

    def grab_attention(self, *, sound: bool = True):
        """Browser equivalent of the desktop grab-attention (flash/sound). Logs a visible prompt instead."""
        self.print("⚠️ Attention: Application requires user interaction")

    def start(self):
        self._running = True

    async def coro_unless_closed(self, coro):
        """Run coro, but raise ExitRequest instead if close() is called first."""
        from exceptions import ExitRequest

        # ensure_future is required in Python 3.11+ to wrap plain awaitables for asyncio.wait.
        tasks = [
            asyncio.ensure_future(coro),
            asyncio.ensure_future(self._close_requested.wait()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if self._close_requested.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def rebuild_ws(self):
        """Rebuild the websocket status display"""
        self.main_panel.rebuild_ws()

    def clear_drop(self):
        """Clear the current drop display"""
        self.main_panel.clear_drop()

    def display_drop(self, drop, *, countdown: bool = True, subone: bool = False):
        """Display current drop information"""
        self.progress.display(drop, countdown=countdown, subone=subone)

    def set_games(self, games: set[Game]) -> None:
        """Set available games for settings"""
        self.settings_panel.set_games(games)

    def apply_theme(self, dark: bool) -> None:
        """Apply theme (no-op for web UI)"""
        pass

    def save(self, *, force: bool = False) -> None:
        """Save GUI state (no-op for web UI)"""
        pass

    def prevent_close(self):
        """Prevent the application from closing (used for error states)"""
        self._close_requested.clear()
        self.print("Application prevented from closing due to error state")

    def update_status(self, text: str) -> None:
        """Update status text across all panels. Single source of truth."""
        self._status_text = text
        self.header_bar.update_status(text)
        self.main_panel.update_status(text)
