from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nicegui import ui, Client

from translate import _
from constants import PriorityMode, State
from .base_panel import BasePanel

if TYPE_CHECKING:
    from nicegui.elements.select import Select as NiceSelect
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
        with ui.row().classes("w-full gap-2 items-stretch flex-wrap"):
            self._build_general_column()
            self._build_priority_column()
            self._build_exclude_column()

    def set_games(self, games: set["Game"]) -> None:
        """Update the available game list and refresh input dropdowns on all clients."""
        self._game_names = {game.name for game in games}
        self._priority_input_content.refresh()
        self._exclude_input_content.refresh()

    def add_priority_game(self, game_name: str) -> None:
        """Add a game to the priority list and rebuild all clients."""
        if not game_name or not game_name.strip():
            return
        settings = self.settings
        if game_name not in settings.priority:
            settings.priority.append(game_name)
            settings.save(force=True)
        self._priority_list_content.refresh()
        self._priority_input_content.refresh()

    def add_excluded_game(self, game_name: str) -> None:
        """Add a game to the exclude list and rebuild all clients."""
        if not game_name or not game_name.strip():
            return
        settings = self.settings
        settings.exclude.add(game_name)
        settings.save(force=True)
        self._exclude_list_content.refresh()
        self._exclude_input_content.refresh()

    # -------------------------------------------------------------------------
    # Private — build helpers
    # -------------------------------------------------------------------------

    def _build_general_column(self) -> None:
        """Left column: General + Advanced + Reload cards."""
        manager = self._manager
        settings = self.settings

        with ui.column().classes("gap-2 grow shrink basis-60 min-w-0"):
            # General section
            with ui.card().props("flat bordered").classes("w-full q-pa-sm"):
                ui.label(_("gui", "settings", "general", "name")).classes(
                    "font-bold text-sm"
                )

                # Language — change triggers a full page reload on all clients,
                # so no cross-client sync is needed beyond that reload.
                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label("Language:").classes("flex-1")
                ui.select(
                    options=list(_.languages),
                    value=_.current,
                    on_change=lambda e: self._on_language_change(e.value),
                ).classes("w-full text-xs").props("dense")

                # Dark mode — bound to settings.dark_mode so all clients
                # reflect changes made by any tab.
                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(_("gui", "settings", "general", "dark_mode")).classes(
                        "flex-1"
                    )
                    ui.switch(
                        value=settings.dark_mode,
                        on_change=lambda e: manager.set_dark_mode(e.value),
                    ).bind_value_from(settings, "dark_mode")

                # Priority mode — bound to settings.priority_mode.
                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(_("gui", "settings", "general", "priority_mode")).classes(
                        "flex-1"
                    )
                ui.select(
                    options=_priority_mode_options(),
                    value=settings.priority_mode,
                    on_change=lambda e: _set_and_save(
                        settings, "priority_mode", e.value
                    ),
                ).classes("w-full text-xs").props("dense").bind_value_from(
                    settings, "priority_mode"
                )

                # Proxy — bound to settings.proxy (URL → str via backward transform).
                ui.label(_("gui", "settings", "general", "proxy")).classes("text-xs")
                ui.input(
                    value=str(settings.proxy) if settings.proxy else "",
                    placeholder="http://username:password@address:port",
                    on_change=lambda e: _on_proxy_change(settings, e.value),
                ).classes("w-full text-xs").props("dense").bind_value_from(
                    settings,
                    "proxy",
                    backward=lambda v: str(v) if v else "",
                )

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
                    ui.switch(
                        value=settings.enable_badges_emotes,
                        on_change=lambda e: _set_and_save(
                            settings, "enable_badges_emotes", e.value
                        ),
                    ).bind_value_from(settings, "enable_badges_emotes")

                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(
                        _("gui", "settings", "advanced", "available_drops_check")
                    ).classes("flex-1")
                    ui.switch(
                        value=settings.available_drops_check,
                        on_change=lambda e: _set_and_save(
                            settings, "available_drops_check", e.value
                        ),
                    ).bind_value_from(settings, "available_drops_check")

            # Reload
            with ui.card().props("flat bordered").classes("w-full q-pa-sm"):
                ui.label(_("gui", "settings", "reload_text")).classes("text-xs")
                ui.button(
                    _("gui", "settings", "reload"),
                    on_click=manager._twitch.state_change(State.INVENTORY_FETCH),
                ).props("dense").classes("text-xs w-full")

    def _build_priority_column(self) -> None:
        """Middle column: priority list with move/delete controls."""
        with (
            ui.card()
            .props("flat bordered")
            .classes("q-pa-sm flex flex-col grow shrink basis-60 min-w-0")
        ):
            ui.label(_("gui", "settings", "priority")).classes("font-bold text-sm")
            self._priority_input_content()
            with ui.row().classes("w-full gap-1 items-start min-h-[200px]"):
                self._priority_list_content()
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

    def _build_exclude_column(self) -> None:
        """Right column: exclude list with delete control."""
        with (
            ui.card()
            .props("flat bordered")
            .classes("q-pa-sm flex flex-col grow shrink basis-60 min-w-0")
        ):
            ui.label(_("gui", "settings", "exclude")).classes("font-bold text-sm")
            self._exclude_input_content()
            with ui.row().classes("w-full gap-1 items-start min-h-[200px]"):
                self._exclude_list_content()
                with ui.column().classes("gap-1"):
                    ui.button("❌", on_click=self._exclude_delete).props(
                        "flat"
                    ).classes("text-red-500 text-xl p-0 min-h-0")

    # -------------------------------------------------------------------------
    # Private — refreshable content methods
    # -------------------------------------------------------------------------

    @ui.refreshable
    def _priority_list_content(self) -> None:
        with (
            ui.list()
            .props("dense bordered")
            .classes("flex-1 text-xs overflow-y-auto min-h-[200px]")
        ):
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

    @ui.refreshable
    def _priority_input_content(self) -> None:
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
            ui.button("➕", on_click=lambda: self._priority_add(priority_input)).props(
                "dense flat"
            ).classes("text-xl p-0 min-h-0")

    @ui.refreshable
    def _exclude_list_content(self) -> None:
        with (
            ui.list()
            .props("dense bordered")
            .classes("flex-1 text-xs overflow-y-auto min-h-[200px]")
        ):
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

    @ui.refreshable
    def _exclude_input_content(self) -> None:
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
            ui.button("➕", on_click=lambda: self._exclude_add(exclude_input)).props(
                "dense flat"
            ).classes("text-xl p-0 min-h-0")

    # -------------------------------------------------------------------------
    # Private — helpers
    # -------------------------------------------------------------------------

    def _priority_options(self) -> list[str]:
        return sorted(self._game_names - set(self.settings.priority))

    def _exclude_options(self) -> list[str]:
        return sorted(self._game_names - self.settings.exclude)

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

    # -------------------------------------------------------------------------
    # Private — priority actions
    # -------------------------------------------------------------------------

    def _priority_select(self, idx: int) -> None:
        self._priority_selected = None if self._priority_selected == idx else idx
        self._priority_list_content.refresh()

    def _priority_add(self, input_el: "NiceSelect") -> None:
        name = input_el.value
        if not name or not str(name).strip():
            return
        name = str(name).strip()
        settings = self.settings
        if name not in settings.priority:
            settings.priority.append(name)
            settings.save(force=True)
        self._priority_list_content.refresh()
        self._priority_input_content.refresh()

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
        self.settings.save(force=True)
        self._priority_selected = new_idx
        self._priority_list_content.refresh()

    def _priority_delete(self) -> None:
        idx = self._priority_selected
        if idx is None:
            return
        priority = self.settings.priority
        if 0 <= idx < len(priority):
            del priority[idx]
            self.settings.save(force=True)
            self._priority_selected = None
            self._priority_list_content.refresh()
            self._priority_input_content.refresh()

    # -------------------------------------------------------------------------
    # Private — exclude actions
    # -------------------------------------------------------------------------

    def _exclude_select(self, name: str) -> None:
        self._exclude_selected = None if self._exclude_selected == name else name
        self._exclude_list_content.refresh()

    def _exclude_add(self, input_el: "NiceSelect") -> None:
        name = input_el.value
        if not name or not str(name).strip():
            return
        name = str(name).strip()
        settings = self.settings
        if name not in settings.exclude:
            settings.exclude.add(name)
            settings.save(force=True)
        self._exclude_list_content.refresh()
        self._exclude_input_content.refresh()

    def _exclude_delete(self) -> None:
        name = self._exclude_selected
        if name is None:
            return
        settings = self.settings
        settings.exclude.discard(name)
        settings.save(force=True)
        self._exclude_selected = None
        self._exclude_list_content.refresh()
        self._exclude_input_content.refresh()


# -------------------------------------------------------------------------
# Settings helpers
# -------------------------------------------------------------------------


def _set_and_save(settings, name: str, value) -> None:
    setattr(settings, name, value)
    settings.save(force=True)


def _on_proxy_change(settings, value: str) -> None:
    from yarl import URL

    try:
        _set_and_save(settings, "proxy", URL(value) if value.strip() else None)
    except Exception:
        pass


def _priority_mode_options() -> dict:
    """Build the priority-mode label map."""
    return {
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
