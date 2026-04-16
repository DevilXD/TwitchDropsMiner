from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from channel import Channel
    from webui.manager import WebUIManager


class ChannelListAdapter:
    """
    Mirrors ChannelList - delegates all state changes to MainPanel's public API.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def clear(self):
        self._manager.main_panel.clear_channels()

    def set_watching(self, channel: "Channel"):
        self._manager.main_panel.set_watching_channel(channel)

    def clear_watching(self):
        self._manager.main_panel.clear_watching_channel()

    def get_selection(self) -> "Channel | None":
        """Return the currently selected Channel (for CHANNEL_SWITCH state)"""
        return self._manager.main_panel.get_selected_channel()

    def clear_selection(self):
        self._manager.main_panel.clear_selection()

    def display(self, channel: "Channel", *, add: bool = False):
        """Add or update a channel entry in the list"""
        self._manager.main_panel.display_channel(channel, add=add)

    def remove(self, channel: "Channel"):
        self._manager.main_panel.remove_channel(channel)
