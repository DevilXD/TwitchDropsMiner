from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _

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
        with ui.header().classes("flex-col items-stretch p-0 gap-0"):
            with ui.row().classes("tdm-header-row w-full items-center q-px-lg q-py-md"):
                ui.image("/icons/pickaxe.ico").classes("w-8 h-8")
                ui.label("Twitch Drops Miner").classes("text-h6")
                ui.space()
                ui.label().classes(
                    "text-body1 q-px-md q-py-xs rounded-borders bg-gray-300 dark:bg-gray-800"
                ).bind_text_from(self._manager, "_status_text")

            with ui.tabs(value=initial_tab, on_change=on_tab_change).classes(
                "w-full"
            ) as tabs:
                ui.tab("main", label=_("gui", "tabs", "main"), icon="home")
                ui.tab(
                    "inventory", label=_("gui", "tabs", "inventory"), icon="inventory"
                )
                ui.tab("settings", label=_("gui", "tabs", "settings"), icon="settings")
                ui.tab("help", label=_("gui", "tabs", "help"), icon="help")

        return tabs
