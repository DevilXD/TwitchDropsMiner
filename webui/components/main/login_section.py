from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class LoginSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._login_status_text: str = f"{_('gui', 'login', 'logged_out')}\n-"
        self._login_btn_visible: bool = False
        self._logout_btn_visible: bool = False

    def build(self) -> None:
        with ui.card().props("flat bordered").classes(
            "gap-1 grow shrink basis-[180px]"
        ):
            ui.label(_("gui", "login", "name")).classes("font-bold text-sm mb-1")
            with ui.row().classes("gap-4 items-start"):
                ui.label(_("gui", "login", "labels")).classes(
                    "text-xs whitespace-pre leading-relaxed"
                )
                ui.label().classes(
                    "text-xs whitespace-pre leading-relaxed"
                ).bind_text_from(self, "_login_status_text")
            ui.button(
                _("gui", "login", "button"),
                on_click=self._manager.login.open_login_popup,
            ).props("dense").classes("text-xs").bind_visibility_from(
                self, "_login_btn_visible"
            )
            ui.button(
                "Logout",
                on_click=self._manager.logout,
            ).props("dense").classes(
                "text-xs"
            ).bind_visibility_from(self, "_logout_btn_visible")
