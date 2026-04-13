from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from channel import Channel
    from webui.manager import WebUIManager


class ChannelListAdapter:
    """
    Mirrors ChannelList - stores channel data on the manager and schedules
    a channel table rebuild on the NiceGUI event loop.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def clear(self):
        panel = self._manager._main_panel
        panel._channel_map.clear()
        panel._watching_channel_iid = None
        panel.rebuild_channel_table()

    def set_watching(self, channel: "Channel"):
        panel = self._manager._main_panel
        panel._watching_channel_iid = channel.iid
        panel.rebuild_channel_table()

    def clear_watching(self):
        panel = self._manager._main_panel
        panel._watching_channel_iid = None
        panel.rebuild_channel_table()

    def get_selection(self) -> "Channel | None":
        """Return the currently selected Channel (for CHANNEL_SWITCH state)"""
        panel = self._manager._main_panel
        iid = panel._selected_channel_iid
        if iid is None:
            return None
        return panel._channel_map.get(iid)

    def clear_selection(self):
        panel = self._manager._main_panel
        panel._selected_channel_iid = None
        panel.clear_selection()

    def display(self, channel: "Channel", *, add: bool = False):
        """Add or update a channel entry in the list"""
        panel = self._manager._main_panel
        iid = channel.iid
        if add:
            panel._channel_map[iid] = channel
        elif iid not in panel._channel_map:
            return
        else:
            panel._channel_map[iid] = channel
        panel.rebuild_channel_table()

    def remove(self, channel: "Channel"):
        panel = self._manager._main_panel
        iid = channel.iid
        panel._channel_map.pop(iid, None)
        if panel._watching_channel_iid == iid:
            panel._watching_channel_iid = None
        panel.rebuild_channel_table()
