from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from .game_list_section import GameListSection

if TYPE_CHECKING:
    from nicegui.elements.input import Input
    from webui.manager import WebUIManager


class ExcludeSection(GameListSection):
    def __init__(self, manager: "WebUIManager") -> None:
        super().__init__(manager)
        self._selected: str | None = None

    def build(self) -> None:
        with (
            ui.card()
            .props("flat bordered")
            .classes("q-pa-sm flex flex-col grow shrink basis-60 min-w-0")
        ):
            ui.label(_("gui", "settings", "exclude")).classes("font-bold text-sm")
            self._input_content()
            with ui.row().classes("w-full gap-1 items-start min-h-[200px]"):
                self._list_content()
                with ui.column().classes("gap-1"):
                    ui.button("❌", on_click=self._on_delete).props("flat").classes(
                        "text-red-500 text-xl p-0 min-h-0"
                    )

    def _options(self) -> list[str]:
        return sorted(self._game_names - self._settings.exclude)

    def _items(self) -> list:
        return sorted(self._settings.exclude)

    def _item_label(self, item: str) -> str:
        return item

    def _is_selected(self, item: str) -> bool:
        return item == self._selected

    def _on_select(self, item: str) -> None:
        self._selected = None if self._selected == item else item
        self._list_content.refresh()

    def _on_delete(self) -> None:
        if self._selected is None:
            return
        self._settings.exclude.discard(self._selected)
        self._settings.save(force=True)
        self._selected = None
        self._list_content.refresh()
        self._input_content.refresh()

    def _do_add(self, name: str, input_el: "Input") -> None:
        if name not in self._settings.exclude:
            self._settings.exclude.add(name)
            self._settings.save(force=True)
        if input_el is not None:
            input_el.set_value("")
        self._list_content.refresh()
        self._input_content.refresh()
