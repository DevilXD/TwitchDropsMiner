# Inventory panel - mirrors gui.py's InventoryOverview exactly
# Campaigns are rendered as raw HTML strings (one ui.html per campaign) to avoid
# creating hundreds of NiceGUI element objects that would overwhelm the WebSocket.

from __future__ import annotations

import html as _html
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


# ---------------------------------------------------------------------------
# Panel creation
# ---------------------------------------------------------------------------

def create_inventory_panel(manager: 'WebUIManager'):
    """Create the inventory panel - mirrors InventoryOverview in gui.py"""
    if not NICEGUI_AVAILABLE:
        return

    with ui.column().classes('w-full gap-2'):

        # Filter bar
        with ui.card().props('flat bordered').classes('w-full q-pa-xs'):
            with ui.row().classes('items-center gap-4 flex-wrap'):
                ui.label(_("gui", "inventory", "filter", "show")).classes('text-sm font-bold')

                manager._filter_checkboxes = {}
                for key in ["not_linked", "upcoming", "expired", "excluded", "finished"]:
                    cb = ui.checkbox(
                        _("gui", "inventory", "filter", key),
                        value=manager._inventory_filters[key],
                        on_change=lambda e, k=key: _on_filter_change(manager, k, e.value),
                    ).classes('text-sm').props('dense')
                    manager._filter_checkboxes[key] = cb

                ui.button(
                    _("gui", "inventory", "filter", "refresh"),
                    on_click=lambda: refresh_inventory(manager),
                ).props('dense').classes('text-sm')

        # Campaign list — uses browser scroll, no inner scroll area
        manager._inventory_container = ui.column().classes('w-full gap-3')
        with manager._inventory_container:
            ui.label("Loading inventory...").classes('text-sm text-gray-500')

    # Flush any campaigns already collected before this client connected
    refresh_inventory_display(manager)

    ui.timer(2.0, lambda: _check_inventory_dirty(manager))


# ---------------------------------------------------------------------------
# Filter logic — exact port of InventoryOverview._update_visibility
# ---------------------------------------------------------------------------

def _campaign_visible(manager: 'WebUIManager', campaign: 'DropsCampaign') -> bool:
    f = manager._inventory_filters
    settings = manager._twitch.settings
    priority_only = settings.priority_mode is PriorityMode.PRIORITY_ONLY
    return (
        campaign.required_minutes > 0
        and (f["not_linked"] or campaign.eligible)
        and (
            campaign.active
            or (f["upcoming"] and campaign.upcoming)
            or (f["expired"]  and campaign.expired)
        )
        and (
            f["excluded"]
            or (
                campaign.game.name not in settings.exclude
                and (not priority_only or campaign.game.name in settings.priority)
            )
        )
        and (f["finished"] or not campaign.finished)
    )


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------

def _e(text) -> str:
    """HTML-escape a value for use in element content."""
    return _html.escape(str(text))


def _ea(text) -> str:
    """HTML-escape a value for use inside an attribute (quotes escaped too)."""
    return _html.escape(str(text), quote=True)


def _drop_progress_text(drop: 'TimedDrop') -> str:
    """Exact port of InventoryOverview.update_progress text logic."""
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
        return '#22c55e'
    if drop.can_claim:
        return '#eab308'
    return 'inherit'


def _render_drop_html(drop: 'TimedDrop') -> str:
    """Render one drop as an HTML string."""
    def _benefit_html(benefit) -> str:
        return (
            '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">'
            f'<div style="font-size:0.75rem;text-align:center;font-weight:500;white-space:nowrap;">{_e(benefit.name)}</div>'
            f'<img src="{_ea(str(benefit.image_url))}" loading="lazy" style="width:80px;height:80px;object-fit:contain;">'
            '</div>'
        )

    drop_id        = _ea(drop.id)
    benefits       = ''.join(_benefit_html(b) for b in drop.benefits)
    progress_text  = _drop_progress_text(drop)
    progress_color = _drop_progress_color(drop)
    progress       = _e(progress_text) if progress_text else '&nbsp;'

    return (
        f'<div id="drop-{drop_id}" class="tdm-drop-card">'
          f'<div style="display:flex;flex-direction:row;flex-wrap:wrap;justify-content:center;gap:10px;">{benefits}</div>'
          f'<div id="drop-progress-{drop_id}" style="font-size:0.75rem;text-align:center;white-space:pre;color:{progress_color};">{progress}</div>'
        '</div>'
    )


def _render_campaign_html(campaign: 'DropsCampaign') -> str:
    """Render one campaign row as a complete HTML string."""
    # Status badge
    if campaign.active:
        status_text, status_color = _("gui", "inventory", "status", "active"),   '#22c55e'
    elif campaign.upcoming:
        status_text, status_color = _("gui", "inventory", "status", "upcoming"), '#eab308'
    else:
        status_text, status_color = _("gui", "inventory", "status", "expired"),  '#ef4444'

    # Dates — shows primary date by default, secondary on hover
    date_html = ''
    try:
        starts = _e(_("gui", "inventory", "starts").format(
            time=campaign.starts_at.astimezone().replace(microsecond=0, tzinfo=None)
        ))
        ends = _e(_("gui", "inventory", "ends").format(
            time=campaign.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
        ))
        primary, secondary = (starts, ends) if campaign.upcoming else (ends, starts)
        date_html = (
            '<div class="tdm-campaign-date" style="font-size:0.75rem;color:#9ca3af;cursor:default;">'
            f'<span class="default">{primary}</span>'
            f'<span class="hovered">{secondary}</span>'
            '</div>'
        )
    except Exception:
        pass

    # Link eligibility
    link_text  = _("gui", "inventory", "status", "linked" if campaign.eligible else "not_linked")
    link_color = '#22c55e' if campaign.eligible else '#ef4444'

    # Allowed channels
    acl = campaign.allowed_channels
    if acl:
        names = [ch.name for ch in acl]
        if len(names) <= 5:
            acl_text = ', '.join(names)
        else:
            acl_text = ', '.join(names[:4]) + ', ' + _("gui", "inventory", "and_more").format(amount=len(acl) - 4)
    else:
        acl_text = _("gui", "inventory", "all_channels")

    # Left column: campaign image + metadata
    info_html = (
        '<div style="flex:0 1 400px;min-width:0;display:flex;flex-direction:row;gap:12px;align-items:flex-start;">'
          f'<img src="{_ea(str(campaign.image_url))}" loading="lazy" style="width:108px;height:144px;object-fit:cover;border-radius:4px;flex-shrink:0;">'
          '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:4px;">'
            f'<div style="font-weight:bold;font-size:0.875rem;">{_e(campaign.name)}</div>'
            f'<div style="font-size:0.75rem;color:#9ca3af;">{_e(campaign.game.name)}</div>'
            f'<div style="font-size:0.75rem;font-weight:bold;color:{status_color};">{_e(status_text)}</div>'
            f'{date_html}'
            f'<a href="{_ea(str(campaign.link_url))}" target="_blank" style="font-size:0.75rem;color:{link_color};text-decoration:underline;">{_e(link_text)}</a>'
            f'<div style="font-size:0.75rem;color:#9ca3af;">{_e(_("gui", "inventory", "allowed_channels"))} {_e(acl_text)}</div>'
          '</div>'
        '</div>'
    )

    drops_html = ''.join(_render_drop_html(d) for d in campaign.drops)

    return (
        '<div class="tdm-campaign-card">'
          f'{info_html}'
          '<div class="tdm-campaign-divider"></div>'
          f'<div style="display:flex;flex-wrap:wrap;gap:8px;flex:1;align-items:flex-start;">{drops_html}</div>'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Display rebuild
# ---------------------------------------------------------------------------

def _check_inventory_dirty(manager: 'WebUIManager'):
    if manager._inventory_dirty:
        manager._inventory_dirty = False
        refresh_inventory_display(manager)


def refresh_inventory(manager: 'WebUIManager'):
    """Re-read campaigns from twitch.inventory and rebuild display."""
    manager._inventory_campaigns.clear()
    manager._campaign_html_elements.clear()

    if hasattr(manager._twitch, 'inventory') and manager._twitch.inventory:
        for campaign in manager._twitch.inventory:
            manager._inventory_campaigns[campaign.id] = campaign

    manager._inventory_dirty = True


def refresh_inventory_display(manager: 'WebUIManager'):
    """Rebuild campaign list — one ui.html() per visible campaign."""
    if manager._inventory_container is None:
        return

    manager._campaign_html_elements.clear()
    manager._inventory_container.clear()

    # Sort matches the three stable sorts in twitch.py fetch_inventory:
    # primary: eligible first, secondary: by date, tertiary: active first
    campaigns = sorted(
        manager._inventory_campaigns.values(),
        key=lambda c: (not c.eligible, c.upcoming and c.starts_at or c.ends_at, not c.active),
    )
    visible = [c for c in campaigns if _campaign_visible(manager, c)]

    with manager._inventory_container:
        if not visible:
            ui.label("No campaigns match the current filters.").classes(
                'text-sm text-gray-500 p-4'
            )
            return

        for campaign in visible:
            elem = ui.html(_render_campaign_html(campaign)).style('width: 100%')
            manager._campaign_html_elements[campaign.id] = elem


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_filter(manager: 'WebUIManager', key: str, value: bool):
    manager._inventory_filters[key] = value
    refresh_inventory_display(manager)


def _on_filter_change(manager: 'WebUIManager', key: str, value: bool):
    update_filter(manager, key, value)
