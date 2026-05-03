from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class InventoryOverviewAdapter:
    """
    Mirrors InventoryOverview - triggers inventory panel refreshes
    when the backend calls clear/add_campaign/update_drop.
    Campaign data is read directly from twitch.inventory.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def clear(self):
        self._manager.inventory_panel.clear()

    async def add_campaign(self, campaign) -> None:
        self._manager.inventory_panel.add_campaign(campaign)

    def update_drop(self, drop) -> None:
        self._manager.inventory_panel.update_drop(drop)

    def configure_theme(self, *, bg: str):
        pass
