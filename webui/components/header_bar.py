from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from nicegui import ui

    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

from translate import _

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class HeaderBar:
    """
    Owns all widget references for the header bar.

    The header is displayed on every tab, so it's built in manager._setup_ui()
    before the tab panels. Status text is owned by the manager (single source
    of truth) - this just manages the widget references.
    """

    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        # Per-client widget refs
        self._client_labels: dict = {}

    def build(self, initial_tab: str, on_tab_change):
        """Build the header UI for the current NiceGUI client."""
        if not NICEGUI_AVAILABLE:
            return

        client_id = ui.context.client.id
        ui.context.client.on_disconnect(
            lambda: self._client_labels.pop(client_id, None)
        )

        # Status text is owned by manager - use it for initial value
        initial_status = self._manager._status_text

        with ui.header().classes("flex-col items-stretch p-0 gap-0"):
            with ui.row().classes("tdm-header-row w-full items-center q-px-lg q-py-md"):
                ui.image("/static/pickaxe.png").classes("w-8 h-8")
                ui.label("Twitch Drops Miner").classes("text-h6")
                ui.space()
                header_label = ui.label(initial_status).classes("text-body1")
                self._client_labels[client_id] = header_label

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

    def update_status(self, text: str) -> None:
        """Update the status text for all connected clients.
        Called by manager.update_status() - manager owns the status text."""
        for label in self._client_labels.values():
            label.set_text(text)
