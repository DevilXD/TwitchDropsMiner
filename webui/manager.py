# Main WebUI Manager class
# Handles the NiceGUI-based web interface that provides the same interface as GUIManager

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

try:
    from nicegui import ui, app
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None
    app = None

from translate import _
from .mock_classes import (MockTray, MockStatus, MockProgress, MockOutput, MockChannels,
                          MockInventory, MockLoginForm, MockWebsocketStatus, MockSettings, MockTabs)
from .handlers import WebUIOutputHandler
from .components import (create_main_panel, create_settings_panel, create_inventory_panel,
                        add_priority_game, add_excluded_game, refresh_inventory, update_filter,
                        clear_drop, display_drop, set_games)

if TYPE_CHECKING:
    from twitch import Twitch
    from yarl import URL


class WebUIManager:
    """
    NiceGUI-based web interface that provides the same interface as GUIManager
    """

    def __init__(self, twitch: 'Twitch', host: str = "127.0.0.1", port: int = 8080):
        if not NICEGUI_AVAILABLE:
            raise ImportError("NiceGUI is not installed. Install it with: pip install nicegui")

        self._twitch: 'Twitch' = twitch
        self._host = host
        self._port = port
        self._close_requested = asyncio.Event()
        self._running = False
        self._console_log = []

        # Create mock objects for compatibility
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

        # Initialize UI components as None - created when each client connects
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
        self._filter_checkboxes = None
        self._inventory_container = None

        # WebSocket state (shared with MockWebsocketStatus)
        self._ws_data: dict = {}        # idx -> {status, topics}
        self._ws_dirty: bool = False

        # Login state
        self._login_status_text: str = (
            f"{_('gui', 'login', 'logged_out')}\n-"
        )
        self._login_dirty: bool = False

        # Channel list state (shared with MockChannels)
        self._channel_map: dict = {}    # iid -> Channel
        self._watching_channel_iid = None
        self._channels_dirty: bool = False

        # Drop/progress state
        self._current_drop = None
        self._countdown_active: bool = False
        self._progress_seconds: int = 0

        # Inventory tracking
        self._inventory_filters = {
            "not_linked": False,
            "upcoming": False,
            "active": False,
            "expired": False,
            "excluded": False,
            "finished": False,
        }
        self._campaigns = {}

        # Setup the UI page
        self._setup_ui()

        # Setup logging handler
        self._handler = WebUIOutputHandler(self)
        logger = logging.getLogger("TwitchDrops")
        logger.addHandler(self._handler)

        # Start the server in a background task
        self._start_server()

    def _start_server(self):
        """Start the NiceGUI server"""
        def run_server():
            try:
                print(f"Starting NiceGUI server on {self._host}:{self._port}")
                ui.run(
                    host=self._host,
                    port=self._port,
                    title="Twitch Drops Miner",
                    show=False,  # Don't auto-open browser
                    reload=False,
                    favicon="🎮"
                )
            except Exception as e:
                print(f"Failed to start NiceGUI server: {e}")

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # Give the server a moment to start
        time.sleep(1)

    def _setup_ui(self):
        """Setup the NiceGUI interface"""
        @ui.page('/')
        def index():
            # Set page title and apply dark theme
            ui.page_title("Twitch Drops Miner")
            ui.dark_mode(True)

            # Store references to self in the outer scope
            manager = self

            with ui.header().classes('bg-gray-900'):
                ui.label("Twitch Drops Miner").classes('text-h4 text-white')
                ui.space()
                with ui.row():
                    manager._status_label = ui.label("Starting...").classes('text-body1 text-white')
                    ui.button("Stop", on_click=manager.close).classes('bg-red-600 hover:bg-red-700')

            # Create tabbed interface
            with ui.tabs().classes('w-full bg-gray-800') as tabs:
                main_tab = ui.tab("Main", icon="home").classes('text-white')
                settings_tab = ui.tab("Settings", icon="settings").classes('text-white')
                inventory_tab = ui.tab("Inventory", icon="inventory").classes('text-white')

            with ui.tab_panels(tabs, value=main_tab).classes('w-full h-full bg-gray-900'):
                # Main tab content - matching original GUI layout
                with ui.tab_panel(main_tab):
                    create_main_panel(manager)

                # Settings tab content
                with ui.tab_panel(settings_tab):
                    create_settings_panel(manager)

                # Inventory tab content
                with ui.tab_panel(inventory_tab):
                    create_inventory_panel(manager)

            # Add initial dark mode styling (will be updated by toggle)
            manager._apply_initial_styles()


    def _toggle_dark_mode(self, enabled: bool):
        """Toggle dark mode on/off"""
        self._dark_mode_enabled = enabled

        # Update NiceGUI dark mode
        ui.dark_mode(enabled)

        # Update the CSS dynamically
        if enabled:
            # Apply dark mode styles
            ui.add_head_html('''
                <style id="dark-mode-styles">
                    body, html { background-color: #1f2937 !important; color: #ffffff !important; }
                    .nicegui-content { background-color: #1f2937 !important; color: #ffffff !important; }
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
            # Apply light mode styles
            ui.add_head_html('''
                <style id="light-mode-styles">
                    body, html { background-color: #ffffff !important; color: #000000 !important; }
                    .nicegui-content { background-color: #ffffff !important; color: #000000 !important; }
                    .q-tab { color: #000000 !important; }
                    .q-tabs { background-color: #f3f4f6 !important; }
                    .q-tab-panels { background-color: #ffffff !important; color: #000000 !important; }
                    .q-field__control { background-color: #f9fafb !important; color: #000000 !important; }
                    .q-field__native { color: #000000 !important; }
                    .q-card { background-color: #f9fafb !important; color: #000000 !important; }
                    .q-expansion-item { background-color: #f9fafb !important; color: #000000 !important; }
                </style>
            ''')

        # Print to console for feedback
        mode_text = "dark" if enabled else "light"
        self.print(f"Theme changed to {mode_text} mode")


    def _apply_initial_styles(self):
        """Apply initial styling based on current dark mode setting"""
        self._toggle_dark_mode(self._dark_mode_enabled)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    def print(self, message: str):
        """Print message to console output"""
        timestamp = datetime.now().strftime("%X")
        formatted_message = f"{timestamp}: {message}"

        # Store in console log for display
        self._console_log.append(formatted_message)

        # Also print to console if available
        if self._console is not None:
            try:
                if '\n' in message:
                    for line in message.split('\n'):
                        if line.strip():
                            self._console.push(f"{timestamp}: {line}")
                else:
                    self._console.push(formatted_message)
            except Exception:
                # Fallback to standard print if UI update fails (e.g., during shutdown)
                print(formatted_message)
        else:
            # Fallback to standard print if UI not ready
            print(formatted_message)

    def close(self, *args) -> int:
        """Request the GUI application to close"""
        self._close_requested.set()
        return 0

    async def wait_until_closed(self):
        """Wait until the user closes the window"""
        await self._close_requested.wait()

    def stop(self):
        """Stop the GUI polling and cleanup"""
        self._running = False

    def close_window(self):
        """Close the window and cleanup"""
        if hasattr(logging.getLogger("TwitchDrops"), 'removeHandler'):
            logging.getLogger("TwitchDrops").removeHandler(self._handler)
        app.shutdown()

    def grab_attention(self, *, sound: bool = True):
        """Grab user attention (web UI equivalent)"""
        # In a web UI, we can't grab attention in the same way
        # But we can update the title or show a notification
        self.print("⚠️  Attention: Application requires user interaction")

    def start(self):
        """Start the web UI"""
        self._running = True

    async def coro_unless_closed(self, coro):
        """Execute coroutine unless the GUI is closed"""
        from exceptions import ExitRequest

        # In Python 3.11, we need to explicitly wrap awaitables
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