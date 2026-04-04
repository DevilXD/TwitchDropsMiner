# Settings panel UI components for the WebUI

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from nicegui import ui
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

from translate import _
from constants import PriorityMode, State

if TYPE_CHECKING:
    from webui.manager import WebUIManager


def create_settings_panel(manager: 'WebUIManager'):
    """Create the settings panel - three columns: general/advanced | priority | exclude"""
    if not NICEGUI_AVAILABLE:
        return

    settings = manager._twitch.settings

    with ui.row().classes('w-full gap-2 items-stretch'):

        # ── Left column: General + Advanced + Reload ──────────────────────────
        with ui.column().classes('gap-2').style('flex: 1; min-width: 0'):

            # General section
            with ui.card().props('flat').classes('w-full q-pa-sm'):
                ui.label(_("gui", "settings", "general", "name")).classes('font-bold text-sm')

                # Language
                with ui.row().classes('items-center gap-2 text-xs'):
                    ui.label("Language 🌐 (requires restart):").classes('flex-1')
                language_select = ui.select(
                    options=list(_.languages),
                    value=_.current,
                    on_change=lambda e: setattr(settings, 'language', e.value),
                ).classes('w-full text-xs').props('dense')

                # Dark mode
                with ui.row().classes('items-center gap-2 text-xs'):
                    ui.label(_("gui", "settings", "general", "dark_mode")).classes('flex-1')
                    ui.switch(value=manager._dark_mode_enabled,
                              on_change=lambda e: manager._toggle_dark_mode(e.value))

                # Priority mode
                priority_mode_options = {
                    PriorityMode.PRIORITY_ONLY:  _("gui", "settings", "priority_modes", "priority_only"),
                    PriorityMode.ENDING_SOONEST: _("gui", "settings", "priority_modes", "ending_soonest"),
                    PriorityMode.LOW_AVBL_FIRST: _("gui", "settings", "priority_modes", "low_availability"),
                }
                with ui.row().classes('items-center gap-2 text-xs'):
                    ui.label(_("gui", "settings", "general", "priority_mode")).classes('flex-1')
                priority_select = ui.select(
                    options=priority_mode_options,
                    value=settings.priority_mode,
                    on_change=lambda e: setattr(settings, 'priority_mode', e.value),
                ).classes('w-full text-xs').props('dense')

                # Proxy
                ui.label(_("gui", "settings", "general", "proxy")).classes('text-xs')
                proxy_input = ui.input(
                    value=str(settings.proxy) if settings.proxy else '',
                    placeholder='http://username:password@address:port',
                    on_change=lambda e: _on_proxy_change(settings, e.value),
                ).classes('w-full text-xs').props('dense')

            # Advanced section
            with ui.card().props('flat').classes('w-full q-pa-sm'):
                ui.label(_("gui", "settings", "advanced", "name")).classes('font-bold text-sm')
                ui.label(_("gui", "settings", "advanced", "warning")).classes('text-xs text-red-500')
                ui.label(_("gui", "settings", "advanced", "warning_text")).classes(
                    'text-xs text-yellow-500 whitespace-pre-wrap'
                )

                with ui.row().classes('items-center gap-2 text-xs'):
                    ui.label(_("gui", "settings", "advanced", "enable_badges_emotes")).classes('flex-1')
                    ui.switch(
                        value=settings.enable_badges_emotes,
                        on_change=lambda e: setattr(settings, 'enable_badges_emotes', e.value),
                    )

                with ui.row().classes('items-center gap-2 text-xs'):
                    ui.label(_("gui", "settings", "advanced", "available_drops_check")).classes('flex-1')
                    ui.switch(
                        value=settings.available_drops_check,
                        on_change=lambda e: setattr(settings, 'available_drops_check', e.value),
                    )

            # Reload
            with ui.card().props('flat').classes('w-full q-pa-sm'):
                ui.label(_("gui", "settings", "reload_text")).classes('text-xs')
                ui.button(
                    _("gui", "settings", "reload"),
                    on_click=manager._twitch.state_change(State.INVENTORY_FETCH),
                ).props('dense').classes('text-xs w-full')

        # ── Middle column: Priority list ───────────────────────────────────────
        with ui.card().props('flat').classes('q-pa-sm flex-col').style('flex: 1; min-width: 0; display: flex'):
            ui.label(_("gui", "settings", "priority")).classes('font-bold text-sm')

            # Input + add
            with ui.row().classes('w-full gap-1 items-center'):
                priority_input = ui.select(
                    options=_get_priority_options(manager),
                    label=_("gui", "settings", "game_name"),
                    new_value_mode='add-unique',
                ).classes('flex-1 text-xs').props('dense use-input hide-selected')
                ui.button('➕', on_click=lambda: _priority_add(manager, priority_input)).props('dense flat')

            # List with move buttons
            with ui.row().classes('w-full gap-1 items-start').style('min-height: 200px'):
                manager._priority_list = ui.list().props('dense bordered').classes(
                    'flex-1 text-xs overflow-y-auto'
                ).style('min-height: 200px')
                _rebuild_priority_list(manager)

                # Move buttons
                with ui.column().classes('gap-1'):
                    ui.button('⇈', on_click=lambda: _priority_move(manager, 'top')).props('dense flat').classes('text-xs')
                    ui.button('↑', on_click=lambda: _priority_move(manager, 'up')).props('dense flat').classes('text-xs')
                    ui.button('↓', on_click=lambda: _priority_move(manager, 'down')).props('dense flat').classes('text-xs')
                    ui.button('⇊', on_click=lambda: _priority_move(manager, 'bottom')).props('dense flat').classes('text-xs')
                    ui.button('❌', on_click=lambda: _priority_delete(manager)).props('dense flat').classes('text-xs text-red-500')

        # ── Right column: Exclude list ─────────────────────────────────────────
        with ui.card().props('flat').classes('q-pa-sm flex-col').style('flex: 1; min-width: 0; display: flex'):
            ui.label(_("gui", "settings", "exclude")).classes('font-bold text-sm')

            # Input + add
            with ui.row().classes('w-full gap-1 items-center'):
                exclude_input = ui.select(
                    options=_get_exclude_options(manager),
                    label=_("gui", "settings", "game_name"),
                    new_value_mode='add-unique',
                ).classes('flex-1 text-xs').props('dense use-input hide-selected')
                ui.button('➕', on_click=lambda: _exclude_add(manager, exclude_input)).props('dense flat')

            # List + delete
            manager._exclude_list = ui.list().props('dense bordered').classes(
                'w-full text-xs overflow-y-auto'
            ).style('min-height: 200px')
            _rebuild_exclude_list(manager)

            ui.button('❌', on_click=lambda: _exclude_delete(manager)).props('dense flat').classes(
                'text-xs text-red-500 w-full'
            )



# ── Helpers ────────────────────────────────────────────────────────────────────

def _on_proxy_change(settings, value: str):
    from yarl import URL
    try:
        settings.proxy = URL(value) if value.strip() else None
    except Exception:
        pass


def _get_priority_options(manager: 'WebUIManager') -> list[str]:
    settings = manager._twitch.settings
    all_games = getattr(manager, '_game_names', set())
    return sorted(all_games - set(settings.priority))


def _get_exclude_options(manager: 'WebUIManager') -> list[str]:
    settings = manager._twitch.settings
    all_games = getattr(manager, '_game_names', set())
    return sorted(all_games - settings.exclude)


def _rebuild_priority_list(manager: 'WebUIManager'):
    if manager._priority_list is None:
        return
    manager._priority_list.clear()
    with manager._priority_list:
        for i, name in enumerate(manager._twitch.settings.priority):
            with ui.item().props('clickable').on('click', lambda _, idx=i: _priority_select(manager, idx)):
                with ui.item_section():
                    ui.item_label(name).classes('text-xs')


def _rebuild_exclude_list(manager: 'WebUIManager'):
    if manager._exclude_list is None:
        return
    manager._exclude_list.clear()
    with manager._exclude_list:
        for name in sorted(manager._twitch.settings.exclude):
            with ui.item().props('clickable').on('click', lambda _, n=name: _exclude_select(manager, n)):
                with ui.item_section():
                    ui.item_label(name).classes('text-xs')


# Selection state (per-manager, stored as attributes)
def _priority_select(manager: 'WebUIManager', idx: int):
    manager._priority_selected = idx


def _exclude_select(manager: 'WebUIManager', name: str):
    manager._exclude_selected = name


def _priority_add(manager: 'WebUIManager', input_el):
    name = input_el.value
    if not name or not str(name).strip():
        return
    name = str(name).strip()
    settings = manager._twitch.settings
    if name not in settings.priority:
        settings.priority.append(name)
        settings.alter()
    input_el.set_value(None)
    _rebuild_priority_list(manager)


def _priority_move(manager: 'WebUIManager', direction: str):
    idx = getattr(manager, '_priority_selected', None)
    priority = manager._twitch.settings.priority
    if idx is None or not priority:
        return
    max_idx = len(priority) - 1
    if direction == 'top':
        new_idx = 0
    elif direction == 'up':
        new_idx = max(0, idx - 1)
    elif direction == 'down':
        new_idx = min(max_idx, idx + 1)
    else:  # bottom
        new_idx = max_idx
    if new_idx == idx:
        return
    item = priority.pop(idx)
    priority.insert(new_idx, item)
    manager._twitch.settings.alter()
    manager._priority_selected = new_idx
    _rebuild_priority_list(manager)


def _priority_delete(manager: 'WebUIManager'):
    idx = getattr(manager, '_priority_selected', None)
    if idx is None:
        return
    priority = manager._twitch.settings.priority
    if 0 <= idx < len(priority):
        del priority[idx]
        manager._twitch.settings.alter()
        manager._priority_selected = None
        _rebuild_priority_list(manager)


def _exclude_add(manager: 'WebUIManager', input_el):
    name = input_el.value
    if not name or not str(name).strip():
        return
    name = str(name).strip()
    settings = manager._twitch.settings
    if name not in settings.exclude:
        settings.exclude.add(name)
        settings.alter()
    input_el.set_value(None)
    _rebuild_exclude_list(manager)


def _exclude_delete(manager: 'WebUIManager'):
    name = getattr(manager, '_exclude_selected', None)
    if name is None:
        return
    settings = manager._twitch.settings
    settings.exclude.discard(name)
    settings.alter()
    manager._exclude_selected = None
    _rebuild_exclude_list(manager)


def add_priority_game(manager: 'WebUIManager', game_name: str):
    """Public API: add a game to the priority list and rebuild."""
    if not game_name or not game_name.strip():
        return
    settings = manager._twitch.settings
    if game_name not in settings.priority:
        settings.priority.append(game_name)
        settings.alter()
    _rebuild_priority_list(manager)


def add_excluded_game(manager: 'WebUIManager', game_name: str):
    """Public API: add a game to the exclude list and rebuild."""
    if not game_name or not game_name.strip():
        return
    settings = manager._twitch.settings
    settings.exclude.add(game_name)
    settings.alter()
    _rebuild_exclude_list(manager)


def set_games(manager: 'WebUIManager', games) -> None:
    """Called when game list is updated — store names for autocomplete."""
    manager._game_names = {game.name for game in games}
