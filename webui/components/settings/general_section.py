from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import app, ui

from translate import _
from constants import PriorityMode, State

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class GeneralSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager

    @property
    def _settings(self):
        return self._manager._twitch.settings

    def build(self) -> None:
        manager = self._manager
        settings = self._settings

        with ui.column().classes("gap-2 grow shrink basis-60 min-w-0"):
            with ui.card().props("flat bordered").classes("w-full q-pa-sm"):
                ui.label(_("gui", "settings", "general", "name")).classes(
                    "font-bold text-sm"
                )

                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label("Language:").classes("flex-1")
                ui.select(
                    options=list(_.languages),
                    value=_.current,
                    on_change=lambda e: self._on_language_change(e.value),
                ).classes("w-full text-xs").props("dense").bind_value_from(_, "current")

                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(_("gui", "settings", "general", "dark_mode")).classes(
                        "flex-1"
                    )
                    ui.switch(
                        value=settings.dark_mode,
                        on_change=lambda e: manager.set_dark_mode(e.value),
                    ).bind_value_from(settings, "dark_mode")

                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(_("gui", "settings", "general", "priority_mode")).classes(
                        "flex-1"
                    )
                ui.select(
                    options=GeneralSection._priority_mode_options(),
                    value=settings.priority_mode,
                    on_change=lambda e: GeneralSection._set_and_save(
                        settings, "priority_mode", e.value
                    ),
                ).classes("w-full text-xs").props("dense").bind_value_from(
                    settings, "priority_mode"
                )

                ui.label(_("gui", "settings", "general", "proxy")).classes("text-xs")
                ui.input(
                    value=str(settings.proxy) if settings.proxy else "",
                    placeholder="http://username:password@address:port",
                    on_change=lambda e: GeneralSection._on_proxy_change(
                        settings, e.value
                    ),
                ).classes("w-full text-xs").props("dense").bind_value_from(
                    settings, "proxy", backward=lambda v: str(v) if v else ""
                )

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
                        on_change=lambda e: GeneralSection._set_and_save(
                            settings, "enable_badges_emotes", e.value
                        ),
                    ).bind_value_from(settings, "enable_badges_emotes")

                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label(
                        _("gui", "settings", "advanced", "available_drops_check")
                    ).classes("flex-1")
                    ui.switch(
                        value=settings.available_drops_check,
                        on_change=lambda e: GeneralSection._set_and_save(
                            settings, "available_drops_check", e.value
                        ),
                    ).bind_value_from(settings, "available_drops_check")

            with ui.card().props("flat bordered").classes("w-full q-pa-sm"):
                ui.label(_("gui", "settings", "reload_text")).classes("text-xs")
                ui.button(
                    _("gui", "settings", "reload"),
                    on_click=manager._twitch.state_change(State.INVENTORY_FETCH),
                ).props("dense").classes("text-xs w-full")

    def _on_language_change(self, language: str) -> None:
        try:
            _.set_language(language)
            GeneralSection._set_and_save(self._settings, "language", language)
            self._reload_all_clients()
            self._manager.restart()
        except ValueError:
            return

    def _reload_all_clients(self) -> None:
        for client in app.clients():
            with client:
                ui.run_javascript("location.reload()")

    @staticmethod
    def _set_and_save(settings, name: str, value) -> None:
        setattr(settings, name, value)
        settings.save(force=True)

    @staticmethod
    def _on_proxy_change(settings, value: str) -> None:
        from yarl import URL

        try:
            GeneralSection._set_and_save(
                settings, "proxy", URL(value) if value.strip() else None
            )
        except Exception:
            pass

    @staticmethod
    def _priority_mode_options() -> dict:
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
