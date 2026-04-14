from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class CampaignProgressAdapter:
    """
    Mirrors CampaignProgress - delegates display() to the main_panel
    display_drop() function via WebUIManager.display_drop().
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def stop_timer(self):
        self._manager.main_panel._countdown_active = False

    def display(self, drop, *, countdown: bool = True, subone: bool = False):
        """Called by twitch.py via GUIManager.display_drop() path"""
        self._manager.main_panel.display_drop(drop, countdown=countdown, subone=subone)

    def minute_almost_done(self) -> bool:
        """True when the countdown timer is at or near 0"""
        panel = self._manager.main_panel
        return not panel._countdown_active or panel._progress_seconds <= 10
