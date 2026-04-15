from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from translate import _

from nicegui import ui

from webui.html_utils import popup_js

if TYPE_CHECKING:
    from yarl import URL
    from webui.manager import WebUIManager


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class LoginFormAdapter:
    """
    Mirrors LoginForm - updates the login status labels and handles
    the device-code activation flow.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager
        self._confirm = asyncio.Event()
        self._page_url: "URL | None" = None

    def clear(self, login: bool = False, password: bool = False, token: bool = False):
        pass

    async def wait_for_login_press(self) -> None:
        self._confirm.clear()
        self._manager.main_panel._login_btn_visible = True
        self._manager.main_panel._logout_btn_visible = False
        self._manager.main_panel.flush_login()
        await self._manager.coro_unless_closed(self._confirm.wait())

    async def ask_login(self) -> LoginData:
        """Deprecated login flow; device-code flow is required."""
        return LoginData("", "", "")

    async def ask_enter_code(self, page_url: "URL", user_code: str) -> None:
        """Show the login button and wait for the user to click it before polling begins."""
        self._page_url = page_url
        self.update(_("gui", "login", "required"), None)
        self._manager.grab_attention(sound=False)
        self._manager.print(_("gui", "login", "request"))
        await self.wait_for_login_press()
        self._page_url = None

    async def open_login_popup(self) -> None:
        """Open the Twitch login URL in a small popup window."""
        if self._page_url is not None:
            js = popup_js(str(self._page_url), "twitch_login")
            await ui.run_javascript(js)
        self._confirm.set()

    def update(self, status: str, user_id: int | None):
        panel = self._manager.main_panel
        user_str = str(user_id) if user_id is not None else "-"
        panel._login_status_text = f"{status}\n{user_str}"
        panel._logout_btn_visible = status == _("gui", "login", "logged_in")
        if status != _("gui", "login", "required"):
            panel._login_btn_visible = False
        panel.flush_login()
        # Mirror login state to the status bar when the main loop hasn't set it yet
        login_statuses = (
            _("gui", "login", "logging_in"),
            _("gui", "login", "required"),
            _("gui", "login", "logged_out"),
        )
        if status in login_statuses:
            self._manager.status.update(status)
