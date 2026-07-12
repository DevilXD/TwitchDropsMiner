from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import app, ui
from yarl import URL

from translate import _
from constants import PriorityMode, State
from webui.html_utils import request_notification_permission_js

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class GeneralSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._proxy_text: str = (
            str(manager._twitch.settings.proxy)
            if manager._twitch.settings.proxy
            else ""
        )

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
                    ui.label(
                        _("gui", "settings", "general", "tray_notifications")
                    ).classes("flex-1")
                    ui.switch(
                        value=settings.tray_notifications,
                        on_change=lambda e: self._on_tray_notifications_change(e.value),
                    ).bind_value_from(settings, "tray_notifications")

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
                    on_change=lambda e: self._on_proxy_change(e.value),
                    validation=lambda v: (
                        "Invalid proxy URL"
                        if not GeneralSection._proxy_is_valid(v)
                        else None
                    ),
                ).classes("w-full text-xs").props("dense").bind_value_from(
                    self, "_proxy_text"
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

                with ui.row().classes("items-center gap-2 text-xs"):
                    ui.label("Mine unlinked games from the Priority List: ").classes(
                        "flex-1"
                    )
                    ui.switch(
                        value=settings.priority_link_override,
                        on_change=lambda e: GeneralSection._set_and_save(
                            settings, "priority_link_override", e.value
                        ),
                    ).bind_value_from(settings, "priority_link_override")

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

    def _on_proxy_change(self, value: str) -> None:
        self._proxy_text = value
        if GeneralSection._proxy_is_valid(value):
            value = value.strip()
            GeneralSection._set_and_save(
                self._settings, "proxy", URL(value) if value else None
            )

    def _on_tray_notifications_change(self, value: bool) -> None:
        GeneralSection._set_and_save(self._settings, "tray_notifications", value)
        if value:
            for client in app.clients():
                with client:
                    ui.run_javascript(request_notification_permission_js())

    @staticmethod
    def _set_and_save(settings, name: str, value) -> None:
        setattr(settings, name, value)
        settings.save(force=True)

    @staticmethod
    def _proxy_is_valid(value: str) -> bool:
        value = value.strip()
        if not value:
            return True
        try:
            url = URL(value)
        except Exception:
            return False
        return url.host is not None and url.port is not None

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
