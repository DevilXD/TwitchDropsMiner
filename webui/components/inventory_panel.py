# Inventory panel - mirrors gui.py's InventoryOverview exactly

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

try:
    from nicegui import ui
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False
    ui = None

from translate import _
from constants import PriorityMode

if TYPE_CHECKING:
    from inventory import DropsCampaign, TimedDrop
    from webui.manager import WebUIManager


def create_inventory_panel(manager: 'WebUIManager'):
    """Create the inventory panel - mirrors InventoryOverview in gui.py"""
    if not NICEGUI_AVAILABLE:
        return

    with ui.column().classes('w-full gap-2 p-2'):

        # Filter bar - mirrors gui.py InventoryOverview filters
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-4 flex-wrap'):
                ui.label(_("gui", "inventory", "filter", "show")).classes('text-sm font-bold')

                manager._filter_checkboxes = {}
                for key, label_key in [
                    ("not_linked", "not_linked"),
                    ("upcoming",   "upcoming"),
                    ("expired",    "expired"),
                    ("excluded",   "excluded"),
                    ("finished",   "finished"),
                ]:
                    cb = ui.checkbox(
                        _("gui", "inventory", "filter", label_key),
                        value=manager._inventory_filters[key],
                        on_change=lambda e, k=key: _on_filter_change(manager, k, e.value),
                    ).classes('text-sm')
                    manager._filter_checkboxes[key] = cb

                ui.button(
                    _("gui", "inventory", "filter", "refresh"),
                    on_click=lambda: refresh_inventory(manager),
                ).props('dense').classes('text-sm')

        # Scrollable campaign list
        with ui.scroll_area().classes('w-full').style('height: calc(100vh - 160px)'):
            manager._inventory_container = ui.column().classes('w-full gap-3')
            with manager._inventory_container:
                ui.label("Loading inventory...").classes('text-sm text-gray-500')

    # Rebuild the display whenever dirty (checked every 2 s)
    ui.timer(2.0, lambda: _check_inventory_dirty(manager))


# ---------------------------------------------------------------------------
# Filter logic - mirrors InventoryOverview._update_visibility exactly
# ---------------------------------------------------------------------------

def _campaign_visible(manager: 'WebUIManager', campaign: 'DropsCampaign') -> bool:
    """Return True if this campaign should be shown under the current filters."""
    f = manager._inventory_filters
    not_linked  = f["not_linked"]
    upcoming    = f["upcoming"]
    expired     = f["expired"]
    excluded    = f["excluded"]
    finished    = f["finished"]

    settings = manager._twitch.settings
    priority_only = settings.priority_mode is PriorityMode.PRIORITY_ONLY

    return (
        campaign.required_minutes > 0
        and (not_linked or campaign.eligible)
        and (
            campaign.active
            or (upcoming and campaign.upcoming)
            or (expired  and campaign.expired)
        )
        and (
            excluded
            or (
                campaign.game.name not in settings.exclude
                and (not priority_only or campaign.game.name in settings.priority)
            )
        )
        and (finished or not campaign.finished)
    )


# ---------------------------------------------------------------------------
# Drop progress text - mirrors InventoryOverview.update_progress exactly
# ---------------------------------------------------------------------------

def _drop_progress_text(drop: 'TimedDrop') -> str:
    """Return the progress text for a single drop."""
    if drop.is_claimed:
        return _("gui", "inventory", "status", "claimed")
    if drop.can_claim:
        return _("gui", "inventory", "status", "ready_to_claim")
    if drop.current_minutes or drop.can_earn():
        text = _("gui", "inventory", "percent_progress").format(
            percent=f"{drop.progress:3.1%}",
            minutes=drop.required_minutes,
        )
        if drop.ends_at < drop.campaign.ends_at:
            text += "\n" + _("gui", "inventory", "ends").format(
                time=drop.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
            )
        return text
    # not started / can't earn
    if drop.required_minutes > 0:
        text = _("gui", "inventory", "minutes_progress").format(
            minutes=drop.required_minutes
        )
    else:
        text = ""
    now = datetime.now(timezone.utc)
    if now < drop.starts_at > drop.campaign.starts_at:
        text += "\n" + _("gui", "inventory", "starts").format(
            time=drop.starts_at.astimezone().replace(microsecond=0, tzinfo=None)
        )
    elif drop.ends_at < drop.campaign.ends_at:
        text += "\n" + _("gui", "inventory", "ends").format(
            time=drop.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
        )
    return text


def _drop_progress_color(drop: 'TimedDrop') -> str:
    if drop.is_claimed:
        return 'text-green-600'
    if drop.can_claim:
        return 'text-yellow-600'
    return ''


# ---------------------------------------------------------------------------
# Display rebuild
# ---------------------------------------------------------------------------

def _check_inventory_dirty(manager: 'WebUIManager'):
    """Called by ui.timer every 2 s. Rebuilds display if dirty."""
    if manager._inventory_dirty:
        manager._inventory_dirty = False
        refresh_inventory_display(manager)


def refresh_inventory(manager: 'WebUIManager'):
    """Re-read campaigns from twitch.inventory and rebuild display. Mirrors refresh()."""
    manager._inventory_campaigns.clear()
    manager._drop_labels.clear()

    if hasattr(manager._twitch, 'inventory') and manager._twitch.inventory:
        for campaign in manager._twitch.inventory:
            manager._inventory_campaigns[campaign.id] = campaign

    manager._inventory_dirty = True


def refresh_inventory_display(manager: 'WebUIManager'):
    """Rebuild the campaign cards from _inventory_campaigns under current filters."""
    if manager._inventory_container is None:
        return

    manager._drop_labels.clear()
    manager._inventory_container.clear()

    campaigns = list(manager._inventory_campaigns.values())
    visible = [c for c in campaigns if _campaign_visible(manager, c)]

    with manager._inventory_container:
        if not visible:
            ui.label(
                "No campaigns match the current filters."
            ).classes('text-sm text-gray-500 p-4')
            return

        for campaign in visible:
            _build_campaign_card(manager, campaign)


def _build_campaign_card(manager: 'WebUIManager', campaign: 'DropsCampaign'):
    """
    One campaign row:
      [campaign image] | campaign info (name, status, dates, link, ACL)
                       | [drop card] [drop card] ...
    """
    with ui.card().classes('w-full').props('flat bordered'):
        with ui.row().classes('w-full items-stretch gap-3 p-2'):

            # --- Campaign image (108 × 144, matching gui.py) ---
            with ui.column().classes('items-center justify-start gap-1 shrink-0'):
                try:
                    ui.image(str(campaign.image_url)).props('loading=lazy').style(
                        'width:108px; height:144px; object-fit:cover; border-radius:4px;'
                    )
                except Exception:
                    ui.icon('image_not_supported').classes('text-gray-400').style(
                        'width:108px; height:144px;'
                    )

            # --- Campaign info column ---
            with ui.column().classes('gap-1 justify-start shrink-0').style('min-width:180px; max-width:220px'):
                ui.label(campaign.name).classes('font-bold text-sm leading-tight')
                ui.label(campaign.game.name).classes('text-xs text-gray-500')

                # Status
                if campaign.active:
                    status_text  = _("gui", "inventory", "status", "active")
                    status_class = 'text-xs font-bold text-green-600'
                elif campaign.upcoming:
                    status_text  = _("gui", "inventory", "status", "upcoming")
                    status_class = 'text-xs font-bold text-yellow-600'
                else:
                    status_text  = _("gui", "inventory", "status", "expired")
                    status_class = 'text-xs font-bold text-red-600'
                ui.label(status_text).classes(status_class)

                # Ends / Starts
                try:
                    ends_local = campaign.ends_at.astimezone().replace(
                        microsecond=0, tzinfo=None
                    )
                    ui.label(
                        _("gui", "inventory", "ends").format(time=ends_local)
                    ).classes('text-xs text-gray-500')
                    if campaign.upcoming:
                        starts_local = campaign.starts_at.astimezone().replace(
                            microsecond=0, tzinfo=None
                        )
                        ui.label(
                            _("gui", "inventory", "starts").format(time=starts_local)
                        ).classes('text-xs text-gray-500')
                except Exception:
                    pass

                # Link status
                link_text  = (
                    _("gui", "inventory", "status", "linked")
                    if campaign.eligible
                    else _("gui", "inventory", "status", "not_linked")
                )
                link_class = 'text-xs ' + ('text-green-600' if campaign.eligible else 'text-red-600')
                ui.link(link_text, campaign.link_url, new_tab=True).classes(link_class)

                # Allowed channels
                acl = campaign.allowed_channels
                if acl:
                    if len(acl) <= 5:
                        acl_text = ", ".join(ch.name for ch in acl)
                    else:
                        acl_text = ", ".join(ch.name for ch in acl[:4])
                        acl_text += ", " + _("gui", "inventory", "and_more").format(
                            amount=len(acl) - 4
                        )
                else:
                    acl_text = _("gui", "inventory", "all_channels")
                ui.label(
                    f"{_('gui', 'inventory', 'allowed_channels')} {acl_text}"
                ).classes('text-xs text-gray-500 leading-tight')

            # --- Vertical divider ---
            ui.separator().props('vertical').classes('self-stretch')

            # --- Drops row (each drop is a sub-card to the right) ---
            with ui.row().classes('items-start gap-2 flex-wrap flex-1'):
                for drop in campaign.drops:
                    _build_drop_card(manager, drop)


def _build_drop_card(manager: 'WebUIManager', drop: 'TimedDrop'):
    """
    One drop sub-card:
      benefit image + name (stacked, one per benefit)
      progress label below
    Mirrors gui.py drop_frame layout.
    """
    with ui.element('div').classes('flex flex-col items-center gap-1 rounded p-3 shrink-0').style('background-color: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.08);'):
        # Benefits: name on top, image (80×80) below
        for benefit in drop.benefits:
            with ui.column().classes('items-center gap-0'):
                ui.label(benefit.name).classes('text-xs text-center font-medium')
                try:
                    ui.image(str(benefit.image_url)).style(
                        'width:80px; height:80px; object-fit:contain;'
                    )
                except Exception:
                    ui.icon('card_giftcard').classes('text-gray-400').style(
                        'width:80px; height:80px;'
                    )

        # Progress label — stored for live updates via update_drop()
        progress_text  = _drop_progress_text(drop)
        progress_class = 'text-xs text-center whitespace-pre ' + _drop_progress_color(drop)
        label = ui.label(progress_text).classes(progress_class)
        manager._drop_labels[drop.id] = label


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_filter(manager: 'WebUIManager', key: str, value: bool):
    """Called by checkbox on_change. Mirrors InventoryOverview filter handling."""
    manager._inventory_filters[key] = value
    refresh_inventory_display(manager)


def _on_filter_change(manager: 'WebUIManager', key: str, value: bool):
    update_filter(manager, key, value)


