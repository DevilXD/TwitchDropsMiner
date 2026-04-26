from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from .base_panel import BasePanel
from .settings import GeneralSection, PrioritySection, ExcludeSection

if TYPE_CHECKING:
    from webui.manager import WebUIManager
    from utils import Game


class SettingsPanel(BasePanel):
    def __init__(self, manager: "WebUIManager"):
        super().__init__(manager)
        self._general_section = GeneralSection(manager)
        self._priority_section = PrioritySection(manager)
        self._exclude_section = ExcludeSection(manager)

    def build(self) -> None:
        with ui.row().classes("w-full gap-2 items-stretch flex-wrap"):
            self._general_section.build()
            self._priority_section.build()
            self._exclude_section.build()

    def set_games(self, games: set["Game"]) -> None:
        self._priority_section.set_games(games)
        self._exclude_section.set_games(games)
