from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from webui.auth import AuthManager

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class HeaderBar:
    """
    Owns the header bar UI for each client.

    Status text is owned by manager._status_text and bound directly —
    no per-client widget tracking needed for the status label.
    """

    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager

    def build(self, initial_tab: str, on_tab_change):
        """Build the header UI for the current NiceGUI client."""
        with ui.header().classes(
            "flex-col items-stretch p-0 gap-0 text-black! dark:text-white!"
        ):
            with ui.row().classes(
                "w-full items-center q-px-lg q-py-md bg-slate-200 dark:bg-slate-900"
            ):
                ui.image("/icons/pickaxe.ico").classes("w-8 h-8")
                ui.label("Twitch Drops Miner").classes("text-h6")
                ui.space()
                ui.label().classes(
                    "text-body1 q-px-md q-py-xs rounded-borders bg-slate-300 dark:bg-slate-800"
                ).bind_text_from(self._manager, "_status_text")
                if AuthManager.AUTH_ENABLED:
                    ui.button(
                        icon="logout",
                        on_click=lambda: ui.run_javascript(AuthManager.logout_js()),
                    ).props("dense flat round").classes("ml-2")

            with ui.tabs(value=initial_tab, on_change=on_tab_change).classes(
                "w-full bg-slate-100 dark:bg-slate-700"
            ) as tabs:
                ui.tab("main", label=_("gui", "tabs", "main"), icon="home")
                ui.tab(
                    "inventory", label=_("gui", "tabs", "inventory"), icon="inventory"
                )
                ui.tab("settings", label=_("gui", "tabs", "settings"), icon="settings")
                ui.tab("help", label=_("gui", "tabs", "help"), icon="help")

        return tabs
