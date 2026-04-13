from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager
    from utils import Game


class SettingsAdapter:
    """
    Mirrors the tkinter SettingsPanel.

    twitch.py calls clear_selection() and set_games() on the settings object;
    those operations are handled directly by the NiceGUI settings panel in
    webui/components/settings_panel.py, so these stubs are intentional no-ops.
    _priority_list / _exclude_list are kept so that any attribute access that
    expects a list-like widget (e.g. configure_theme) does not raise.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager
        self._priority_list = _ListAdapter()
        self._exclude_list = _ListAdapter()

    def clear_selection(self):
        pass

    def set_games(self, games: set[Game]):
        pass


class _ListAdapter:
    """Stub for tkinter Listbox-like objects that only need configure_theme."""

    def configure_theme(self, **kwargs):
        pass
