# Settings panel UI components for the WebUI
# Contains the settings tab with language, theme, priority, and game management

from typing import TYPE_CHECKING

try:
    from nicegui import ui
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

if TYPE_CHECKING:
    from webui.manager import WebUIManager


def create_settings_panel(manager: 'WebUIManager'):
    """Create the settings panel content"""
    if not NICEGUI_AVAILABLE:
        return

    with ui.row().classes('w-full gap-4 p-4'):
        # Left column - General settings
        with ui.column().classes('w-1/2'):
            with ui.card().props('flat').classes('bg-gray-800 border-gray-700'):
                ui.label("General Settings").classes('text-h6 text-white mb-4')

                # Language setting
                with ui.row().classes('items-center gap-4 mb-4'):
                    ui.label("Language 🌐:").classes('text-white w-32')
                    language_select = ui.select(
                        options=['en', 'es', 'fr', 'de', 'pt', 'ru', 'zh'],
                        value='en'
                    ).classes('bg-gray-700 text-white')

                # Dark mode setting
                with ui.row().classes('items-center gap-4 mb-4'):
                    ui.label("Dark Mode:").classes('text-white w-32')
                    dark_mode_switch = ui.switch(value=manager._dark_mode_enabled, on_change=lambda e: manager._toggle_dark_mode(e.value)).classes('text-white')
                    ui.label("(Controls web UI theme)").classes('text-gray-400 text-sm')

                # Priority mode setting
                with ui.row().classes('items-center gap-4 mb-4'):
                    ui.label("Priority Mode:").classes('text-white w-32')
                    priority_select = ui.select(
                        options={
                            'priority_only': 'Priority Only',
                            'ending_soonest': 'Ending Soonest',
                            'low_availability': 'Low Availability First'
                        },
                        value='priority_only'
                    ).classes('bg-gray-700 text-white')

                # Proxy setting
                with ui.row().classes('items-center gap-4 mb-4'):
                    ui.label("Proxy URL:").classes('text-white w-32')
                    proxy_input = ui.input(
                        placeholder="http://username:password@address:port"
                    ).classes('bg-gray-700 text-white flex-1')

        # Right column - Game exclusions and priority
        with ui.column().classes('w-1/2'):
            with ui.card().props('flat').classes('bg-gray-800 border-gray-700'):
                ui.label("Game Management").classes('text-h6 text-white mb-4')

                # Priority games section
                with ui.expansion("Priority Games", icon="star").classes('text-white mb-4'):
                    ui.label("Games to prioritize for drops").classes('text-gray-300 mb-2')
                    manager._priority_list = ui.column().classes('gap-2')
                    with ui.row().classes('gap-2'):
                        priority_input = ui.input(placeholder="Add game name").classes('bg-gray-700 text-white flex-1')
                        ui.button("Add", on_click=lambda: add_priority_game(manager, priority_input.value)).classes('bg-blue-600')

                # Excluded games section
                with ui.expansion("Excluded Games", icon="block").classes('text-white'):
                    ui.label("Games to exclude from drops").classes('text-gray-300 mb-2')
                    manager._exclude_list = ui.column().classes('gap-2')
                    with ui.row().classes('gap-2'):
                        exclude_input = ui.input(placeholder="Add game name").classes('bg-gray-700 text-white flex-1')
                        ui.button("Add", on_click=lambda: add_excluded_game(manager, exclude_input.value)).classes('bg-red-600')

    # Initialize settings values from the actual settings
    _initialize_settings_values(manager, language_select, priority_select, proxy_input, dark_mode_switch)

    # Add change handlers for settings
    _setup_settings_handlers(manager, language_select, priority_select, proxy_input)


def _initialize_settings_values(manager: 'WebUIManager', language_select, priority_select, proxy_input, dark_mode_switch):
    """Initialize settings values from the actual settings"""
    if hasattr(manager._twitch, 'settings'):
        settings = manager._twitch.settings
        try:
            if hasattr(settings, 'language'):
                language_select.set_value(settings.language)
            if hasattr(settings, 'priority_mode'):
                priority_mode_map = {
                    'PRIORITY_ONLY': 'priority_only',
                    'ENDING_SOONEST': 'ending_soonest',
                    'LOW_AVBL_FIRST': 'low_availability'
                }
                priority_select.set_value(priority_mode_map.get(str(settings.priority_mode), 'priority_only'))
            if hasattr(settings, 'proxy') and settings.proxy:
                proxy_input.set_value(str(settings.proxy))
            if hasattr(settings, 'dark_mode'):
                manager._dark_mode_enabled = settings.dark_mode
                dark_mode_switch.set_value(settings.dark_mode)
        except Exception as e:
            print(f"Failed to load settings values: {e}")


def _setup_settings_handlers(manager: 'WebUIManager', language_select, priority_select, proxy_input):
    """Setup change handlers for settings controls"""
    def on_language_change(e):
        if hasattr(manager._twitch, 'settings'):
            manager._twitch.settings.language = e.value
            manager.print(f"Language changed to: {e.value}")

    def on_priority_change(e):
        if hasattr(manager._twitch, 'settings'):
            priority_mode_reverse_map = {
                'priority_only': 'PRIORITY_ONLY',
                'ending_soonest': 'ENDING_SOONEST',
                'low_availability': 'LOW_AVBL_FIRST'
            }
            manager._twitch.settings.priority_mode = priority_mode_reverse_map.get(e.value, 'PRIORITY_ONLY')
            manager.print(f"Priority mode changed to: {e.value}")

    def on_proxy_change(e):
        if hasattr(manager._twitch, 'settings'):
            manager._twitch.settings.proxy = e.value
            manager.print(f"Proxy changed to: {e.value}")

    language_select.on('update:model-value', on_language_change)
    priority_select.on('update:model-value', on_priority_change)
    proxy_input.on('update:model-value', on_proxy_change)


def add_priority_game(manager: 'WebUIManager', game_name: str):
    """Add a game to the priority list"""
    if not NICEGUI_AVAILABLE:
        return

    if game_name and game_name.strip():
        with manager._priority_list:
            with ui.row().classes('items-center gap-2'):
                ui.label(game_name.strip()).classes('text-white flex-1')
                ui.button("Remove", on_click=lambda: remove_priority_game(manager, game_name)).classes('bg-red-600 text-xs')


def remove_priority_game(manager: 'WebUIManager', game_name: str):
    """Remove a game from the priority list"""
    # In a real implementation, this would remove from the UI and update settings
    pass


def add_excluded_game(manager: 'WebUIManager', game_name: str):
    """Add a game to the excluded list"""
    if not NICEGUI_AVAILABLE:
        return

    if game_name and game_name.strip():
        with manager._exclude_list:
            with ui.row().classes('items-center gap-2'):
                ui.label(game_name.strip()).classes('text-white flex-1')
                ui.button("Remove", on_click=lambda: remove_excluded_game(manager, game_name)).classes('bg-red-600 text-xs')


def remove_excluded_game(manager: 'WebUIManager', game_name: str):
    """Remove a game from the excluded list"""
    # In a real implementation, this would remove from the UI and update settings
    pass


def set_games(manager: 'WebUIManager', games) -> None:
    """Set available games for settings (no-op for web UI)"""
    pass