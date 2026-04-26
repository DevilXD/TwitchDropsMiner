from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class LoginSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._login_status_text: str = "\n-"
        self._login_state: str = ""
        self._btn_enabled: bool = True

    def update(self, status: str, user_id: int | None) -> None:
        user_str = str(user_id) if user_id is not None else "-"
        self._login_status_text = f"{status}\n{user_str}"
        self._login_state = status
        self._btn_enabled = True

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
                on_click=self._on_btn_click,
            ).props(
                "dense"
            ).classes("text-xs").bind_text_from(
                self,
                "_login_state",
                backward=lambda s: (
                    "Logout"
                    if s == _("gui", "login", "logged_in")
                    else _("gui", "login", "button")
                ),
            ).bind_visibility_from(
                self,
                "_login_state",
                backward=lambda s: s
                in (
                    _("gui", "login", "logged_in"),
                    _("gui", "login", "required"),
                ),
            ).bind_enabled_from(
                self, "_btn_enabled"
            )

    async def _on_btn_click(self) -> None:
        self._btn_enabled = False
        if self._login_state == _("gui", "login", "logged_in"):
            self._manager.logout()
        else:
            await self._manager.login.open_login_popup()
            self._btn_enabled = True
