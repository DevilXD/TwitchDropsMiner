from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from .game_list_section import GameListSection

if TYPE_CHECKING:
    from nicegui.elements.input import Input
    from webui.manager import WebUIManager


class PrioritySection(GameListSection):
    def __init__(self, manager: "WebUIManager") -> None:
        super().__init__(manager)
        self._selected: int | None = None

    def build(self) -> None:
        with (
            ui.card()
            .props("flat bordered")
            .classes("q-pa-sm flex flex-col grow shrink basis-60 min-w-0")
        ):
            ui.label(_("gui", "settings", "priority")).classes("font-bold text-sm")
            self._input_content()
            with ui.row().classes("w-full gap-1 items-start min-h-[200px]"):
                self._list_content()
                with ui.column().classes("gap-1"):
                    ui.button("⏫", on_click=lambda: self._move("top")).props(
                        "flat"
                    ).classes("text-xl p-0 min-h-0")
                    ui.button("⬆️", on_click=lambda: self._move("up")).props(
                        "flat"
                    ).classes("text-xl p-0 min-h-0")
                    ui.button("⬇️", on_click=lambda: self._move("down")).props(
                        "flat"
                    ).classes("text-xl p-0 min-h-0")
                    ui.button("⏬", on_click=lambda: self._move("bottom")).props(
                        "flat"
                    ).classes("text-xl p-0 min-h-0")
                    ui.button("❌", on_click=self._on_delete).props("flat").classes(
                        "text-red-500 text-xl p-0 min-h-0"
                    )

    def _options(self) -> list[str]:
        return sorted(self._game_names - set(self._settings.priority))

    def _items(self) -> list[tuple[int, str]]:
        return list(enumerate(self._settings.priority))

    def _item_label(self, item: tuple[int, str]) -> str:
        _, name = item
        return name

    def _is_selected(self, item: tuple[int, str]) -> bool:
        idx, _ = item
        return idx == self._selected

    def _on_select(self, item: tuple[int, str]) -> None:
        idx, _ = item
        self._selected = None if self._selected == idx else idx
        self._list_content.refresh()

    def _on_delete(self) -> None:
        if self._selected is None:
            return
        priority = self._settings.priority
        if 0 <= self._selected < len(priority):
            del priority[self._selected]
            self._settings.save(force=True)
            self._selected = None
            self._list_content.refresh()
            self._input_content.refresh()

    def _do_add(self, name: str, input_el: "Input") -> None:
        if name not in self._settings.priority:
            self._settings.priority.append(name)
            self._settings.save(force=True)
        if input_el is not None:
            input_el.set_value("")
        self._list_content.refresh()
        self._input_content.refresh()

    def _move(self, direction: str) -> None:
        idx = self._selected
        priority = self._settings.priority
        if idx is None or not priority:
            return
        max_idx = len(priority) - 1
        if direction == "top":
            new_idx = 0
        elif direction == "up":
            new_idx = max(0, idx - 1)
        elif direction == "down":
            new_idx = min(max_idx, idx + 1)
        else:
            new_idx = max_idx
        if new_idx == idx:
            return
        item = priority.pop(idx)
        priority.insert(new_idx, item)
        self._settings.save(force=True)
        self._selected = new_idx
        self._list_content.refresh()
