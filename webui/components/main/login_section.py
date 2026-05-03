from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import app, ui

from translate import _
from webui.html_utils import close_popup_js, popup_js

if TYPE_CHECKING:
    from webui.manager import WebUIManager

_LOGIN_KEYS = ("logged_in", "logging_in", "required", "logged_out")


class LoginSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._login_state: str = ""
        self._user_str: str = "-"
        self._btn_enabled: bool = True
        self._popup_maybe_open: bool = False

    def update(self, status: str, user_id: int | None) -> None:
        self._login_state = self._key_for_status(status)
        self._user_str = str(user_id) if user_id is not None else "-"
        self._btn_enabled = True
        if self._popup_maybe_open and self._login_state == "logged_in":
            self._close_login_popup()

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
                ).bind_text_from(
                    self,
                    "_login_state",
                    backward=lambda s: (
                        _("gui", "login", s) + "\n" + self._user_str
                        if s in _LOGIN_KEYS
                        else "\n-"
                    ),
                )
            ui.button(
                on_click=self._on_btn_click,
            ).props(
                "dense"
            ).classes("text-xs").bind_text_from(
                self,
                "_login_state",
                backward=lambda s: (
                    "Logout" if s == "logged_in" else _("gui", "login", "button")
                ),
            ).bind_visibility_from(
                self,
                "_login_state",
                backward=lambda s: s in ("logged_in", "required"),
            ).bind_enabled_from(
                self, "_btn_enabled"
            )

    async def _open_login_popup(self) -> None:
        url = self._manager.login.page_url
        if url is not None:
            self._popup_maybe_open = True
            blocked = not await ui.run_javascript(popup_js(str(url), "twitch_login"))
            if blocked:
                self._manager.print(f"{str(url)}")
        self._manager.login.confirm()

    def _close_login_popup(self) -> None:
        self._popup_maybe_open = False
        js = close_popup_js("twitch_login")
        for client in app.clients():
            with client:
                ui.run_javascript(js)

    async def _on_btn_click(self) -> None:
        if self._login_state == "logged_in":
            self._btn_enabled = False
            self._manager.logout()
        else:
            await self._open_login_popup()

    @staticmethod
    def _key_for_status(status: str) -> str:
        for key in _LOGIN_KEYS:
            if status == _("gui", "login", key):
                return key
        return ""
