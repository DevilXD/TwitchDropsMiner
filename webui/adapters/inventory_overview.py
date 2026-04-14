from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class InventoryOverviewAdapter:
    """
    Mirrors InventoryOverview - stores DropsCampaign objects and schedules
    inventory panel rebuilds on the NiceGUI event loop.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager

    def clear(self):
        self._manager.inventory_panel.clear()

    async def add_campaign(self, campaign) -> None:
        """Delegates to InventoryPanel.add_campaign."""
        self._manager.inventory_panel.add_campaign(campaign)

    def update_drop(self, drop) -> None:
        """Mirrors InventoryOverview.update_drop() - delegates to InventoryPanel."""
        self._manager.inventory_panel.update_drop(drop)

    def configure_theme(self, *, bg: str):
        pass
