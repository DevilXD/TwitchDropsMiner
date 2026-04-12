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
#   1. Mock* objects (see mock_classes.py) – one per tkinter widget class
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
# running for a while. All mutable UI state is persisted on the manager
# (status text, console log, channel map, inventory, …) so that a fresh page
# load can rebuild the full current view without waiting for the next update.

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

try:
    from nicegui import ui, app
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None
    app = None

from translate import _
from constants import OUTPUT_FORMATTER, FILE_FORMATTER, WINDOW_TITLE
from .mock_classes import (MockTray, MockStatus, MockProgress, MockOutput, MockChannels,
                          MockInventory, MockLoginForm, MockWebsocketStatus, MockSettings, MockTabs)
from .handlers import WebUIOutputHandler
from .components import (BasePanel, MainPanel, InventoryPanel, HelpPanel, SettingsPanel)

if TYPE_CHECKING:
    from twitch import Twitch
    from utils import Game


class WebUIManager:
    """
    NiceGUI-based web interface that is a drop-in replacement for the tkinter GUIManager.

    WebUIManager owns:
    - The NiceGUI HTTP server (started in a daemon thread by _start_server).
    - All shared mutable UI state (status text, console log, channel map, …)
      that the Mock* attribute objects write to and the NiceGUI timer reads from.
    - The top-level methods (print, close, display_drop, …) called directly by
      twitch.py on the manager object.

    The Mock* objects stored as attributes mirror the tkinter widget classes that
    twitch.py expects (self.status → StatusBar, self.channels → ChannelList, …).
    See mock_classes.py for details.
    """

    def __init__(self, twitch: 'Twitch'):
        if not NICEGUI_AVAILABLE:
            raise ImportError("NiceGUI is not installed. Install it with: pip install nicegui")

        self._twitch: 'Twitch' = twitch
        self._close_requested = asyncio.Event()
        self._running = False
        self._console_log = []

        self.tray = MockTray(self)
        self.status = MockStatus(self)
        self.progress = MockProgress(self)
        self.output = MockOutput(self)
        self.channels = MockChannels(self)
        self.inv = MockInventory(self)
        self.login = MockLoginForm(self)
        self.websockets = MockWebsocketStatus(self)
        self.settings = MockSettings(self)
        self.tabs = MockTabs()

        # Panel objects — own all widget references and state for their tab
        self._main_panel: MainPanel = MainPanel(self)
        self._settings_panel: BasePanel = SettingsPanel(self)
        self._inventory_panel: BasePanel = InventoryPanel(self)
        self._help_panel: BasePanel = HelpPanel(self)

        # Dark mode state — read from settings so the correct value is applied on every page load
        self._dark_mode_enabled: bool = twitch.settings.dark_mode

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
        app.add_static_files('/static', str(Path(__file__).parent / 'static'))
        _css = (Path(__file__).parent / 'styles.css').read_text(encoding='utf-8')

        @ui.page('/')
        def index(tab: str = 'main'):
            ui.page_title(WINDOW_TITLE)
            ui.dark_mode(self._dark_mode_enabled)
            ui.query('.nicegui-content').classes('p-0')
            ui.add_head_html(f'<style>{_css}</style>')

            # Alias so nested closures below can reference the manager unambiguously.
            manager = self
            client_id = ui.context.client.id

            # Fall back to 'main' if the ?tab= query param is not a known tab name.
            initial_tab = tab if tab in ('main', 'inventory', 'settings', 'help') else 'main'

            with ui.header().classes('flex-col items-stretch p-0 gap-0'):
                with ui.row().classes('tdm-header-row w-full items-center q-px-lg q-py-md'):
                    ui.image('/static/pickaxe.png').classes('w-8 h-8')
                    ui.label("Twitch Drops Miner").classes('text-h6')
                    ui.space()
                    header_label = ui.label("Starting...").classes('text-body1')

                def _on_tab_change(e):
                    t = str(e.value)
                    ui.run_javascript(f"history.replaceState(null, '', '?tab={t}')")

                with ui.tabs(value=initial_tab, on_change=_on_tab_change).classes('w-full') as tabs:
                    main_tab      = ui.tab('main',      label=_('gui', 'tabs', 'main'),      icon='home')
                    inventory_tab = ui.tab('inventory', label=_('gui', 'tabs', 'inventory'), icon='inventory')
                    settings_tab  = ui.tab('settings',  label=_('gui', 'tabs', 'settings'),  icon='settings')
                    help_tab      = ui.tab('help',      label=_('gui', 'tabs', 'help'),      icon='help')

            with ui.tab_panels(tabs, value=initial_tab).classes('w-full h-full'):
                with ui.tab_panel(main_tab):
                    manager._main_panel.build()

                with ui.tab_panel(inventory_tab):
                    manager._inventory_panel.build()

                with ui.tab_panel(settings_tab):
                    manager._settings_panel.build()

                with ui.tab_panel(help_tab):
                    manager._help_panel.build()

            # Register header label after build() so the client entry already exists
            manager._main_panel.register_header_label(client_id, header_label)


    def _toggle_dark_mode(self, enabled: bool):
        """Apply dark mode to the current client's page and schedule it for all other clients."""
        self._dark_mode_enabled = enabled
        ui.dark_mode(enabled)
        try:
            current_id = ui.context.client.id
        except Exception:
            current_id = None
        from nicegui import Client
        async def _apply(client) -> None:
            with client:
                ui.dark_mode(enabled)
        for client_id, client in list(Client.instances.items()):
            if client_id != current_id:
                asyncio.get_event_loop().create_task(_apply(client))

    @property
    def running(self) -> bool:
        return self._running

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    def print(self, message: str):
        """Append a timestamped line to the in-browser console log.
        Matches gui.py ConsoleOutput.print(): each line of a multiline message gets its own stamp."""
        stamp = datetime.now().strftime("%X")
        if '\n' in message:
            display_message = message.replace('\n', f"\n{stamp}: ")
        else:
            display_message = message

        lines = [f"{stamp}: {line}" for line in display_message.split('\n')]
        # Persist every line so late-joining clients can replay the full log on connect.
        self._console_log.extend(lines)

        # Direct call since we're on the same event loop now
        self._main_panel.push_console(lines)

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
        self.print("⚠️  Attention: Application requires user interaction")

    def start(self):
        self._running = True

    async def coro_unless_closed(self, coro):
        """Run coro, but raise ExitRequest instead if close() is called first."""
        from exceptions import ExitRequest

        # ensure_future is required in Python 3.11+ to wrap plain awaitables for asyncio.wait.
        tasks = [asyncio.ensure_future(coro), asyncio.ensure_future(self._close_requested.wait())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if self._close_requested.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def rebuild_ws(self):
        """Rebuild the websocket status display"""
        self._main_panel.rebuild_ws()

    def clear_drop(self):
        """Clear the current drop display"""
        self._main_panel.clear_drop()

    def display_drop(self, drop, *, countdown: bool = True, subone: bool = False):
        """Display current drop information"""
        self._main_panel.display_drop(drop, countdown=countdown, subone=subone)

    def set_games(self, games: set[Game]) -> None:
        """Set available games for settings"""
        self._settings_panel.set_games(games)

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
