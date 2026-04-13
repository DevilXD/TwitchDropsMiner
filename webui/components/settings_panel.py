from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

try:
    from nicegui import ui, Client

    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None
    Client = None

from translate import _
from constants import PriorityMode, State
from .base_panel import BasePanel

if TYPE_CHECKING:
    from nicegui.elements.input import Input as NiceInput
    from nicegui.elements.list import List as NiceList
    from nicegui.elements.select import Select as NiceSelect
    from nicegui.elements.switch import Switch as NiceSwitch
    from webui.manager import WebUIManager
    from utils import Game


class SettingsPanel(BasePanel):
    """
    Owns all widget references and mutable state for the settings tab.

    One instance lives on WebUIManager. Each browser client calls build(),
    which stores that client's widget references in per-widget dicts keyed by
    client ID. State (selection, game names) is shared across all tabs — the
    last action wins and every tab is kept in sync.
    """

    def __init__(self, manager: "WebUIManager"):
        super().__init__(manager)

        # Per-client widget refs (keyed by NiceGUI client ID).
        # Stale entries for disconnected clients are harmlessly skipped by
        # checking Client.instances in the broadcast helpers.

        # General column
        self._language_selects: dict[str, "NiceSelect"] = {}
        self._dark_mode_switches: dict[str, "NiceSwitch"] = {}
        self._priority_mode_selects: dict[str, "NiceSelect"] = {}
        self._proxy_inputs: dict[str, "NiceInput"] = {}
        self._enable_badges_switches: dict[str, "NiceSwitch"] = {}
        self._available_drops_switches: dict[str, "NiceSwitch"] = {}

        # Priority / exclude columns
        self._priority_lists: dict[str, "NiceList"] = {}
        self._exclude_lists: dict[str, "NiceList"] = {}
        self._priority_inputs: dict[str, "NiceSelect"] = {}
        self._exclude_inputs: dict[str, "NiceSelect"] = {}

        # Shared state — all connected tabs see the same values
        self._priority_selected: int | None = None
        self._exclude_selected: str | None = None
        self._game_names: set[str] = set()

    @property
    def settings(self):
        return self._manager._twitch.settings

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def build(self) -> None:
        """Build the settings panel UI for the current NiceGUI client."""
        if not NICEGUI_AVAILABLE:
            return

        client_id = ui.context.client.id
        ui.context.client.on_disconnect(lambda: self._remove_client(client_id))

        with ui.row().classes("w-full gap-2 items-stretch flex-wrap"):
            self._build_general_column(client_id)
            self._build_priority_column(client_id)
            self._build_exclude_column(client_id)

    def set_games(self, games: set["Game"]) -> None:
        """Update the available game list and refresh input dropdowns.
        Called on the NiceGUI event loop via manager.set_games()."""
        self._game_names = {game.name for game in games}
        self._refresh_input_options()

    def add_priority_game(self, game_name: str) -> None:
        """Add a game to the priority list and rebuild all clients."""
        if not game_name or not game_name.strip():
            return
        settings = self.settings
        if game_name not in settings.priority:
            settings.priority.append(game_name)
            settings.alter()
            settings.save()
        self._rebuild_priority_list()

    def add_excluded_game(self, game_name: str) -> None:
        """Add a game to the exclude list and rebuild all clients."""
        if not game_name or not game_name.strip():
            return
        settings = self.settings
        settings.exclude.add(game_name)
        settings.alter()
        settings.save()
        self._rebuild_exclude_list()

    # -------------------------------------------------------------------------
    # Private — client lifecycle
    # -------------------------------------------------------------------------

    def _remove_client(self, client_id: str) -> None:
        """Drop all widget refs for a disconnected client."""
        self._language_selects.pop(client_id, None)
        self._dark_mode_switches.pop(client_id, None)
        self._priority_mode_selects.pop(client_id, None)
        self._proxy_inputs.pop(client_id, None)
        self._enable_badges_switches.pop(client_id, None)
        self._available_drops_switches.pop(client_id, None)
        self._priority_lists.pop(client_id, None)
        self._exclude_lists.pop(client_id, None)
        self._priority_inputs.pop(client_id, None)
        self._exclude_inputs.pop(client_id, None)

    # -------------------------------------------------------------------------
    # Private — build helpers
    # -------------------------------------------------------------------------

    def _build_general_column(self, client_id: str) -> None:
        """Left column: General + Advanced + Reload cards."""
        manager = self._manager
        settings = self.settings

        with ui.column().classes("gap-2 grow shrink basis-60 min-w-0"):
            # General section
            with ui.card().props("flat bordered").classes("w-full q-pa-sm"):
                ui.label(_("gui", "settings", "general", "name")).classes(
                    "font-bold text-sm"
                )

                # Language
                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label("Language:").classes("flex-1")
                language_select = (
                    ui.select(
                        options=list(_.languages),
                        value=_.current,
                        on_change=lambda e: self._on_language_change(e.value),
                    )
                    .classes("w-full text-xs")
                    .props("dense")
                )
                self._language_selects[client_id] = language_select

                # Dark mode
                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(_("gui", "settings", "general", "dark_mode")).classes(
                        "flex-1"
                    )
                    dark_switch = ui.switch(
                        value=manager._dark_mode_enabled,
                        on_change=lambda e: (
                            _set_and_save(settings, "dark_mode", e.value),
                            manager.toggle_dark_mode(e.value),
                            self._sync_others(
                                self._dark_mode_switches, client_id, e.value
                            ),
                        ),
                    )
                    self._dark_mode_switches[client_id] = dark_switch

                # Priority mode
                priority_mode_options = {
                    PriorityMode.PRIORITY_ONLY: _(
                        "gui", "settings", "priority_modes", "priority_only"
                    ),
                    PriorityMode.ENDING_SOONEST: _(
                        "gui", "settings", "priority_modes", "ending_soonest"
                    ),
                    PriorityMode.LOW_AVBL_FIRST: _(
                        "gui", "settings", "priority_modes", "low_availability"
                    ),
                }
                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(_("gui", "settings", "general", "priority_mode")).classes(
                        "flex-1"
                    )
                priority_mode_select = (
                    ui.select(
                        options=priority_mode_options,
                        value=settings.priority_mode,
                        on_change=lambda e: (
                            _set_and_save(settings, "priority_mode", e.value),
                            self._sync_others(
                                self._priority_mode_selects, client_id, e.value
                            ),
                        ),
                    )
                    .classes("w-full text-xs")
                    .props("dense")
                )
                self._priority_mode_selects[client_id] = priority_mode_select

                # Proxy
                ui.label(_("gui", "settings", "general", "proxy")).classes("text-xs")
                proxy_input = (
                    ui.input(
                        value=str(settings.proxy) if settings.proxy else "",
                        placeholder="http://username:password@address:port",
                        on_change=lambda e: (
                            _on_proxy_change(settings, e.value),
                            self._sync_others(self._proxy_inputs, client_id, e.value),
                        ),
                    )
                    .classes("w-full text-xs")
                    .props("dense")
                )
                self._proxy_inputs[client_id] = proxy_input

            # Advanced section
            with ui.card().props("flat bordered").classes("w-full q-pa-sm"):
                ui.label(_("gui", "settings", "advanced", "name")).classes(
                    "font-bold text-sm"
                )
                ui.label(_("gui", "settings", "advanced", "warning")).classes(
                    "text-xs text-red-500"
                )
                ui.label(_("gui", "settings", "advanced", "warning_text")).classes(
                    "text-xs text-yellow-500 whitespace-pre-wrap"
                )

                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(
                        _("gui", "settings", "advanced", "enable_badges_emotes")
                    ).classes("flex-1")
                    enable_badges_switch = ui.switch(
                        value=settings.enable_badges_emotes,
                        on_change=lambda e: (
                            _set_and_save(settings, "enable_badges_emotes", e.value),
                            self._sync_others(
                                self._enable_badges_switches, client_id, e.value
                            ),
                        ),
                    )
                    self._enable_badges_switches[client_id] = enable_badges_switch

                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(
                        _("gui", "settings", "advanced", "available_drops_check")
                    ).classes("flex-1")
                    available_drops_switch = ui.switch(
                        value=settings.available_drops_check,
                        on_change=lambda e: (
                            _set_and_save(settings, "available_drops_check", e.value),
                            self._sync_others(
                                self._available_drops_switches, client_id, e.value
                            ),
                        ),
                    )
                    self._available_drops_switches[client_id] = available_drops_switch

            # Reload
            with ui.card().props("flat bordered").classes("w-full q-pa-sm"):
                ui.label(_("gui", "settings", "reload_text")).classes("text-xs")
                ui.button(
                    _("gui", "settings", "reload"),
                    on_click=manager._twitch.state_change(State.INVENTORY_FETCH),
                ).props("dense").classes("text-xs w-full")

    def _build_priority_column(self, client_id: str) -> None:
        """Middle column: priority list with move/delete controls."""
        with (
            ui.card()
            .props("flat bordered")
            .classes("q-pa-sm flex flex-col grow shrink basis-60 min-w-0")
        ):
            ui.label(_("gui", "settings", "priority")).classes("font-bold text-sm")

            with ui.row().classes("w-full gap-1 items-center"):
                priority_input = (
                    ui.select(
                        options=self._priority_options(),
                        label=_("gui", "settings", "game_name"),
                        new_value_mode="add-unique",
                    )
                    .classes("flex-1 text-xs")
                    .props("dense use-input hide-selected")
                )
                self._priority_inputs[client_id] = priority_input
                ui.button(
                    "➕", on_click=lambda: self._priority_add(priority_input)
                ).props("dense flat").classes("text-xl p-0 min-h-0")

            with ui.row().classes("w-full gap-1 items-start min-h-[200px]"):
                priority_list = (
                    ui.list()
                    .props("dense bordered")
                    .classes("flex-1 text-xs overflow-y-auto min-h-[200px]")
                )
                self._priority_lists[client_id] = priority_list
                self._do_rebuild_priority_list(priority_list)

                with ui.column().classes("gap-1"):
                    ui.button("⏫", on_click=lambda: self._priority_move("top")).props(
                        "flat"
                    ).classes("text-xl p-0 min-h-0")
                    ui.button("⬆️", on_click=lambda: self._priority_move("up")).props(
                        "flat"
                    ).classes("text-xl p-0 min-h-0")
                    ui.button("⬇️", on_click=lambda: self._priority_move("down")).props(
                        "flat"
                    ).classes("text-xl p-0 min-h-0")
                    ui.button(
                        "⏬", on_click=lambda: self._priority_move("bottom")
                    ).props("flat").classes("text-xl p-0 min-h-0")
                    ui.button("❌", on_click=self._priority_delete).props(
                        "flat"
                    ).classes("text-red-500 text-xl p-0 min-h-0")

    def _build_exclude_column(self, client_id: str) -> None:
        """Right column: exclude list with delete control."""
        with (
            ui.card()
            .props("flat bordered")
            .classes("q-pa-sm flex flex-col grow shrink basis-60 min-w-0")
        ):
            ui.label(_("gui", "settings", "exclude")).classes("font-bold text-sm")

            with ui.row().classes("w-full gap-1 items-center"):
                exclude_input = (
                    ui.select(
                        options=self._exclude_options(),
                        label=_("gui", "settings", "game_name"),
                        new_value_mode="add-unique",
                    )
                    .classes("flex-1 text-xs")
                    .props("dense use-input hide-selected")
                )
                self._exclude_inputs[client_id] = exclude_input
                ui.button(
                    "➕", on_click=lambda: self._exclude_add(exclude_input)
                ).props("dense flat").classes("text-xl p-0 min-h-0")

            with ui.row().classes("w-full gap-1 items-start min-h-[200px]"):
                exclude_list = (
                    ui.list()
                    .props("dense bordered")
                    .classes("flex-1 text-xs overflow-y-auto min-h-[200px]")
                )
                self._exclude_lists[client_id] = exclude_list
                self._do_rebuild_exclude_list(exclude_list)

                with ui.column().classes("gap-1"):
                    ui.button("❌", on_click=self._exclude_delete).props(
                        "flat"
                    ).classes("text-red-500 text-xl p-0 min-h-0")

    # -------------------------------------------------------------------------
    # Private — per-widget rebuild
    # -------------------------------------------------------------------------

    def _do_rebuild_priority_list(self, priority_list: "NiceList") -> None:
        priority_list.clear()
        with priority_list:
            for i, name in enumerate(self.settings.priority):
                active = i == self._priority_selected
                with (
                    ui.item()
                    .props(f"clickable {'active' if active else ''}")
                    .classes("bg-primary text-white" if active else "")
                    .on("click", lambda _, idx=i: self._priority_select(idx))
                ):
                    with ui.item_section():
                        ui.item_label(name).classes("text-xs")

    def _do_rebuild_exclude_list(self, exclude_list: "NiceList") -> None:
        exclude_list.clear()
        with exclude_list:
            for name in sorted(self.settings.exclude):
                active = name == self._exclude_selected
                with (
                    ui.item()
                    .props(f"clickable {'active' if active else ''}")
                    .classes("bg-primary text-white" if active else "")
                    .on("click", lambda _, n=name: self._exclude_select(n))
                ):
                    with ui.item_section():
                        ui.item_label(name).classes("text-xs")

    # -------------------------------------------------------------------------
    # Private — broadcast helpers
    # -------------------------------------------------------------------------

    def _priority_options(self) -> list[str]:
        return sorted(self._game_names - set(self.settings.priority))

    def _exclude_options(self) -> list[str]:
        return sorted(self._game_names - self.settings.exclude)

    def _current_client_id(self) -> str | None:
        try:
            return ui.context.client.id
        except Exception:
            return None

    def _on_language_change(self, language: str) -> None:
        """Switch the active language and reload every connected browser tab.
        The page reload re-runs build() with the new _.current, so all labels
        and dropdowns render in the new language without restarting the server."""
        _set_and_save(self.settings, "language", language)
        try:
            _.set_language(language)
        except ValueError:
            return
        self._reload_all_clients()

    def _reload_all_clients(self) -> None:
        """Send location.reload() to every connected NiceGUI browser tab."""
        from nicegui import ui, Client

        try:
            current_id: str | None = ui.context.client.id
        except Exception:
            current_id = None

        async def _reload(client) -> None:
            with client:
                ui.run_javascript("location.reload()")

        for client_id, client in list(Client.instances.items()):
            if client_id == current_id:
                ui.run_javascript("location.reload()")
            else:
                asyncio.get_event_loop().create_task(_reload(client))

    def _sync_others(self, widget_dict: dict, source_id: str, value) -> None:
        """Push a new value to every connected client's copy of a widget,
        skipping the source client (which already reflects the change)."""
        for client_id, widget in list(widget_dict.items()):
            if client_id == source_id:
                continue
            if Client.instances.get(client_id) is None:
                continue
            asyncio.get_event_loop().create_task(
                self._async_set_value(Client.instances[client_id], widget, value)
            )

    def _rebuild_priority_list(self) -> None:
        """Rebuild the priority list widget on every connected tab."""
        current_id = self._current_client_id()
        for client_id, priority_list in list(self._priority_lists.items()):
            if Client.instances.get(client_id) is None:
                continue
            if client_id == current_id:
                self._do_rebuild_priority_list(priority_list)
            else:
                asyncio.get_event_loop().create_task(
                    self._async_rebuild_priority(
                        Client.instances[client_id], priority_list
                    )
                )

    def _rebuild_exclude_list(self) -> None:
        """Rebuild the exclude list widget on every connected tab."""
        current_id = self._current_client_id()
        for client_id, exclude_list in list(self._exclude_lists.items()):
            if Client.instances.get(client_id) is None:
                continue
            if client_id == current_id:
                self._do_rebuild_exclude_list(exclude_list)
            else:
                asyncio.get_event_loop().create_task(
                    self._async_rebuild_exclude(
                        Client.instances[client_id], exclude_list
                    )
                )

    def _refresh_input_options(self) -> None:
        """Refresh autocomplete options on every connected tab."""
        priority_opts = self._priority_options()
        exclude_opts = self._exclude_options()
        current_id = self._current_client_id()
        all_ids = set(self._priority_inputs) | set(self._exclude_inputs)
        for client_id in list(all_ids):
            if Client.instances.get(client_id) is None:
                continue
            p_input = self._priority_inputs.get(client_id)
            e_input = self._exclude_inputs.get(client_id)
            if client_id == current_id:
                if p_input is not None:
                    p_input.options = priority_opts
                    p_input.update()
                if e_input is not None:
                    e_input.options = exclude_opts
                    e_input.update()
            else:
                asyncio.get_event_loop().create_task(
                    self._async_refresh_inputs(
                        Client.instances[client_id],
                        p_input,
                        e_input,
                        priority_opts,
                        exclude_opts,
                    )
                )

    async def _async_set_value(self, client, widget, value) -> None:
        with client:
            widget.set_value(value)

    async def _async_rebuild_priority(self, client, priority_list: "NiceList") -> None:
        with client:
            self._do_rebuild_priority_list(priority_list)

    async def _async_rebuild_exclude(self, client, exclude_list: "NiceList") -> None:
        with client:
            self._do_rebuild_exclude_list(exclude_list)

    async def _async_refresh_inputs(
        self,
        client,
        p_input: "NiceSelect | None",
        e_input: "NiceSelect | None",
        priority_opts: list,
        exclude_opts: list,
    ) -> None:
        with client:
            if p_input is not None:
                p_input.options = priority_opts
                p_input.update()
            if e_input is not None:
                e_input.options = exclude_opts
                e_input.update()

    # -------------------------------------------------------------------------
    # Private — priority actions
    # -------------------------------------------------------------------------

    def _priority_select(self, idx: int) -> None:
        self._priority_selected = None if self._priority_selected == idx else idx
        self._rebuild_priority_list()

    def _priority_add(self, input_el: "NiceSelect") -> None:
        name = input_el.value
        if not name or not str(name).strip():
            return
        name = str(name).strip()
        settings = self.settings
        if name not in settings.priority:
            settings.priority.append(name)
            settings.alter()
            settings.save()
        input_el.set_value(None)
        self._rebuild_priority_list()
        self._refresh_input_options()

    def _priority_move(self, direction: str) -> None:
        idx = self._priority_selected
        priority = self.settings.priority
        if idx is None or not priority:
            return
        max_idx = len(priority) - 1
        if direction == "top":
            new_idx = 0
        elif direction == "up":
            new_idx = max(0, idx - 1)
        elif direction == "down":
            new_idx = min(max_idx, idx + 1)
        else:  # bottom
            new_idx = max_idx
        if new_idx == idx:
            return
        item = priority.pop(idx)
        priority.insert(new_idx, item)
        self.settings.alter()
        self.settings.save()
        self._priority_selected = new_idx
        self._rebuild_priority_list()

    def _priority_delete(self) -> None:
        idx = self._priority_selected
        if idx is None:
            return
        priority = self.settings.priority
        if 0 <= idx < len(priority):
            del priority[idx]
            self.settings.alter()
            self.settings.save()
            self._priority_selected = None
            self._rebuild_priority_list()
            self._refresh_input_options()

    # -------------------------------------------------------------------------
    # Private — exclude actions
    # -------------------------------------------------------------------------

    def _exclude_select(self, name: str) -> None:
        self._exclude_selected = None if self._exclude_selected == name else name
        self._rebuild_exclude_list()

    def _exclude_add(self, input_el: "NiceSelect") -> None:
        name = input_el.value
        if not name or not str(name).strip():
            return
        name = str(name).strip()
        settings = self.settings
        if name not in settings.exclude:
            settings.exclude.add(name)
            settings.alter()
            settings.save()
        input_el.set_value(None)
        self._rebuild_exclude_list()
        self._refresh_input_options()

    def _exclude_delete(self) -> None:
        name = self._exclude_selected
        if name is None:
            return
        settings = self.settings
        settings.exclude.discard(name)
        settings.alter()
        settings.save()
        self._exclude_selected = None
        self._rebuild_exclude_list()
        self._refresh_input_options()


# -------------------------------------------------------------------------
# Settings helpers
# -------------------------------------------------------------------------


def _set_and_save(settings, name: str, value) -> None:
    setattr(settings, name, value)
    settings.save()


def _on_proxy_change(settings, value: str) -> None:
    from yarl import URL

    try:
        settings.proxy = URL(value) if value.strip() else None
        settings.save()
    except Exception:
        pass
