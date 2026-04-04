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
# Dirty-flag / deferred-update pattern
# --------------------------------------
# NiceGUI's DOM can only be mutated from inside the server's asyncio event loop.
# twitch.py calls come from a *different* context, so direct widget writes would
# race. Instead every Mock* method writes to plain Python state stored on the
# manager (e.g. _ws_data, _channel_map) and sets a boolean "dirty" flag
# (e.g. _ws_dirty, _channels_dirty). A ui.timer running inside the NiceGUI
# event loop checks these flags periodically and flushes the pending updates.
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
import threading
import time
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
from constants import PriorityMode, OUTPUT_FORMATTER, FILE_FORMATTER
from .mock_classes import (MockTray, MockStatus, MockProgress, MockOutput, MockChannels,
                          MockInventory, MockLoginForm, MockWebsocketStatus, MockSettings, MockTabs)
from .handlers import WebUIOutputHandler
from .components import (create_main_panel, create_settings_panel, create_inventory_panel,
                        create_help_panel, add_priority_game, add_excluded_game,
                        refresh_inventory, update_filter, clear_drop, display_drop, set_games)

if TYPE_CHECKING:
    from twitch import Twitch
    from yarl import URL


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

    def __init__(self, twitch: 'Twitch', host: str = "127.0.0.1", port: int = 8080):
        if not NICEGUI_AVAILABLE:
            raise ImportError("NiceGUI is not installed. Install it with: pip install nicegui")

        self._twitch: 'Twitch' = twitch
        self._host = host
        self._port = port
        self._main_loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        self._close_requested = asyncio.Event()
        self._running = False
        self._console_log = []

        self.tray = MockTray()
        self.status = MockStatus(self)
        self.progress = MockProgress(self)
        self.output = MockOutput(self)
        self.channels = MockChannels(self)
        self.inv = MockInventory(self)
        self.login = MockLoginForm(self)
        self.websockets = MockWebsocketStatus(self)
        self.settings = MockSettings(self)
        self.tabs = MockTabs()

        # Current status text (persisted so late-joining clients can restore it)
        self._status_text: str = "Initializing..."

        # NiceGUI widget references — None until the first client page load populates them.
        # Each browser connection runs the index() handler which assigns these.
        self._status_label = None
        self._status_card = None
        self._console = None
        self._dark_mode_enabled = True

        # Main panel UI elements
        self._ws_container = None
        self._login_status_label = None
        self._campaign_game_label = None
        self._campaign_name_label = None
        self._campaign_progress_bar = None
        self._campaign_percentage_label = None
        self._campaign_remaining_label = None
        self._drop_rewards_label = None
        self._drop_progress_bar = None
        self._drop_percentage_label = None
        self._drop_remaining_label = None
        self._channels_table = None
        self._channel_switch_btn = None

        # Settings/inventory UI elements
        self._priority_list = None
        self._exclude_list = None
        self._priority_input = None
        self._exclude_input = None
        self._filter_checkboxes = None
        self._inventory_container = None
        self._priority_selected: int | None = None
        self._exclude_selected: str | None = None
        self._game_names: set = set()

        # WebSocket state (shared with MockWebsocketStatus)
        self._ws_data: dict = {}        # idx -> {status, topics}
        self._ws_dirty: bool = False

        # Login state
        self._login_status_text: str = (
            f"{_('gui', 'login', 'logged_out')}\n-"
        )
        self._login_dirty: bool = False
        self._login_btn_visible: bool = False
        self._logout_btn_visible: bool = False
        self._login_button = None
        self._logout_button = None

        # Channel list state (shared with MockChannels)
        self._channel_map: dict = {}    # iid -> Channel
        self._watching_channel_iid = None
        self._channels_dirty: bool = False

        # Drop/progress state
        self._current_drop = None
        self._countdown_active: bool = False
        self._progress_seconds: int = 0

        # Inventory tracking
        # Defaults match gui.py InventoryOverview.__init__:
        # not_linked = True when priority_mode is PRIORITY_ONLY, upcoming = True, rest False
        _priority_only = twitch.settings.priority_mode is PriorityMode.PRIORITY_ONLY
        self._inventory_filters: dict = {
            "not_linked": _priority_only,
            "upcoming":   True,
            "expired":    False,
            "excluded":   False,
            "finished":   False,
        }
        self._inventory_campaigns: dict = {}        # campaign.id -> DropsCampaign
        self._campaign_html_elements: dict = {}     # campaign.id -> ui.html element
        self._inventory_dirty: bool = False

        self._setup_ui()

        # Use the same log formatter as gui.py's _TKOutputHandler so messages look identical.
        self._handler = WebUIOutputHandler(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logger = logging.getLogger("TwitchDrops")
        logger.addHandler(self._handler)
        if (logging_level := logger.getEffectiveLevel()) < logging.ERROR:
            self.print(f"Logging level: {logging.getLevelName(logging_level)}")

        self._start_server()

    def _start_server(self):
        """Start the NiceGUI server in a daemon thread so it doesn't block the main loop."""
        def run_server():
            try:
                print(f"Starting NiceGUI server on {self._host}:{self._port}")
                ui.run(
                    host=self._host,
                    port=self._port,
                    title="Twitch Drops Miner",
                    show=False,  # Don't auto-open browser
                    reload=False,
                    favicon=Path(__file__).parent / 'static' / 'pickaxe.ico'
                )
            except Exception as e:
                print(f"Failed to start NiceGUI server: {e}")

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # Brief wait so the server is accepting connections before twitch.py continues.
        time.sleep(1)

    def _setup_ui(self):
        """Register the NiceGUI page handler. The inner index() function runs once
        per browser connection, building the full UI for that client."""
        app.add_static_files('/static', str(Path(__file__).parent / 'static'))

        @ui.page('/')
        def index(tab: str = 'main'):
            ui.page_title("Twitch Drops Miner")
            ui.dark_mode(True)
            ui.query('.nicegui-content').style('padding: 0')
            ui.add_head_html('''<style>
                .tdm-campaign-card {
                    border: 1px solid rgba(0,0,0,0.12);
                    background: rgba(0,0,0,0.03);
                    border-radius: 8px;
                    padding: 10px;
                    display: flex;
                    gap: 12px;
                    align-items: flex-start;
                    width: 100%;
                    box-sizing: border-box;
                }
                body.body--dark .tdm-campaign-card {
                    border-color: rgba(255,255,255,0.28);
                    background: rgba(255,255,255,0.05);
                }
                .tdm-drop-card {
                    border: 1px solid rgba(0,0,0,0.12);
                    background: rgba(0,0,0,0.06);
                    border-radius: 4px;
                    padding: 12px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 6px;
                    flex-shrink: 0;
                }
                body.body--dark .tdm-drop-card {
                    border-color: rgba(255,255,255,0.28);
                    background: rgba(0,0,0,0.2);
                }
                .tdm-campaign-divider {
                    width: 1px;
                    background: rgba(0,0,0,0.12);
                    align-self: stretch;
                    flex-shrink: 0;
                }
                body.body--dark .tdm-campaign-divider {
                    background: rgba(255,255,255,0.28);
                }
            </style>''')

            # Alias so nested closures below can reference the manager unambiguously.
            manager = self

            # Fall back to 'main' if the ?tab= query param is not a known tab name.
            initial_tab = tab if tab in ('main', 'inventory', 'settings', 'help') else 'main'

            with ui.header().classes('flex-col items-stretch p-0 gap-0'):
                with ui.row().classes('tdm-header-row w-full items-center q-px-lg q-py-md'):
                    ui.image('/static/pickaxe.png').classes('w-8 h-8')
                    ui.label("Twitch Drops Miner").classes('text-h6')
                    ui.space()
                    manager._status_label = ui.label("Starting...").classes('text-body1')

                def _on_tab_change(e):
                    t = str(e.value)
                    ui.run_javascript(f"history.replaceState(null, '', '?tab={t}')")

                with ui.tabs(value=initial_tab, on_change=_on_tab_change).classes('w-full') as tabs:
                    main_tab      = ui.tab('main',      label='Main',      icon='home')
                    inventory_tab = ui.tab('inventory', label='Inventory', icon='inventory')
                    settings_tab  = ui.tab('settings',  label='Settings',  icon='settings')
                    help_tab      = ui.tab('help',      label=_('gui', 'tabs', 'help'), icon='help')

            with ui.tab_panels(tabs, value=initial_tab).classes('w-full h-full'):
                with ui.tab_panel(main_tab):
                    create_main_panel(manager)

                with ui.tab_panel(inventory_tab):
                    create_inventory_panel(manager)

                with ui.tab_panel(settings_tab):
                    create_settings_panel(manager)

                with ui.tab_panel(help_tab):
                    create_help_panel(manager)

            # Add initial dark mode styling (will be updated by toggle)
            manager._apply_initial_styles()


    def _toggle_dark_mode(self, enabled: bool):
        """Switch dark/light mode. NiceGUI's ui.dark_mode() flips Quasar's body class,
        but Quasar component colours need explicit CSS overrides to follow suit."""
        self._dark_mode_enabled = enabled
        ui.dark_mode(enabled)
        if enabled:
            ui.add_head_html('''
                <style id="dark-mode-styles">
                    body, html { background-color: #1f2937 !important; color: #ffffff !important; }
                    .nicegui-content { background-color: #1f2937 !important; color: #ffffff !important; }
                    .tdm-header-row { color: #ffffff !important; background-color: #111827 !important; }
                    .q-tab { color: #ffffff !important; }
                    .q-tabs { background-color: #374151 !important; }
                    .q-tab-panels { background-color: #1f2937 !important; color: #ffffff !important; }
                    .q-field__control { background-color: #374151 !important; color: #ffffff !important; }
                    .q-field__native { color: #ffffff !important; }
                    .q-card { background-color: #374151 !important; color: #ffffff !important; }
                    .q-expansion-item { background-color: #374151 !important; color: #ffffff !important; }
                </style>
            ''')
        else:
            ui.add_head_html('''
                <style id="light-mode-styles">
                    body, html { background-color: #ffffff !important; color: #000000 !important; }
                    .nicegui-content { background-color: #ffffff !important; color: #000000 !important; }
                    .tdm-header-row { color: #000000 !important; background-color: #E5E7EB !important; }
                    .q-tab { color: #000000 !important; }
                    .q-tabs { background-color: #f3f4f6 !important; }
                    .q-tab-panels { background-color: #ffffff !important; color: #000000 !important; }
                    .q-field__control { background-color: #f9fafb !important; color: #000000 !important; }
                    .q-field__native { color: #000000 !important; }
                    .q-card { background-color: #f9fafb !important; color: #000000 !important; }
                    .q-expansion-item { background-color: #f9fafb !important; color: #000000 !important; }
                </style>
            ''')

    def _apply_initial_styles(self):
        self._toggle_dark_mode(self._dark_mode_enabled)

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
        # Prefix every line so multiline messages are readable in the log view.
        if '\n' in message:
            display_message = message.replace('\n', f"\n{stamp}: ")
        else:
            display_message = message

        # Persist every line so late-joining clients can replay the full log on connect.
        for line in display_message.split('\n'):
            self._console_log.append(f"{stamp}: {line}")

        if self._console is not None:
            try:
                for line in display_message.split('\n'):
                    self._console.push(f"{stamp}: {line}")
            except Exception:
                pass

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
        if hasattr(logging.getLogger("TwitchDrops"), 'removeHandler'):
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

    def clear_drop(self):
        """Clear the current drop display"""
        clear_drop(self)

    def display_drop(self, drop, *, countdown: bool = True, subone: bool = False):
        """Display current drop information"""
        display_drop(self, drop, countdown=countdown, subone=subone)

    def set_games(self, games) -> None:
        """Set available games for settings"""
        set_games(self, games)

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