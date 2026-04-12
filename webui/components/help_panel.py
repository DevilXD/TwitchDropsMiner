# Help panel UI components for the WebUI

from __future__ import annotations

try:
    from nicegui import ui
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

from translate import _
from .base_panel import BasePanel


class HelpPanel(BasePanel):
    def build(self) -> None:
        if not NICEGUI_AVAILABLE:
            return

        with ui.column().classes('w-full gap-2 items-center'):
            with ui.column().classes('gap-2 w-full max-w-[1000px]'):

                # About
                with ui.card().props('flat bordered').classes('w-full q-pa-sm'):
                    ui.label("About").classes('font-bold text-sm')
                    with ui.grid(columns='auto 1fr').classes('gap-x-4 gap-y-1 text-sm'):
                        ui.label("Application created by:").classes('text-right')
                        ui.link("DevilXD/fireph", "https://github.com/DevilXD", True).classes('text-sm')

                        ui.label("Repository:").classes('text-right')
                        ui.link(
                            "https://github.com/fireph/docker-twitch-drops-miner",
                            "https://github.com/fireph/docker-twitch-drops-miner",
                            True,
                        ).classes('text-sm')

                    ui.separator().classes('my-1')

                    with ui.grid(columns='auto 1fr').classes('gap-x-4 text-sm'):
                        ui.label("Donate:").classes('text-right')
                        ui.link(
                            "If you like the application and found it useful, "
                            "please consider donating a small amount of money to support me. Thank you!",
                            "https://www.buymeacoffee.com/DevilXD",
                            True,
                        ).classes('text-sm')

                # Useful Links
                with ui.card().props('flat bordered').classes('w-full q-pa-sm'):
                    ui.label(_("gui", "help", "links", "name")).classes('font-bold text-sm')
                    ui.link(
                        _("gui", "help", "links", "inventory"),
                        "https://www.twitch.tv/drops/inventory",
                        True,
                    ).classes('text-sm')
                    ui.link(
                        _("gui", "help", "links", "campaigns"),
                        "https://www.twitch.tv/drops/campaigns",
                        True,
                    ).classes('text-sm')

                # How It Works
                with ui.card().props('flat bordered').classes('w-full q-pa-sm'):
                    ui.label(_("gui", "help", "how_it_works")).classes('font-bold text-sm')
                    ui.label(_("gui", "help", "how_it_works_text")).classes('text-sm')

                # Getting Started
                with ui.card().props('flat bordered').classes('w-full q-pa-sm'):
                    ui.label(_("gui", "help", "getting_started")).classes('font-bold text-sm')
                    ui.label(_("gui", "help", "getting_started_text")).classes(
                        'text-sm whitespace-pre-wrap'
                    )
