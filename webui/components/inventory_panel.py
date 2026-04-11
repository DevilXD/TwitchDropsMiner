# Inventory panel - mirrors gui.py's InventoryOverview exactly
# Campaigns are rendered as raw HTML strings (one ui.html per campaign) to avoid
# creating hundreds of NiceGUI element objects that would overwhelm the WebSocket.

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
from webui.html_utils import Tag

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


def _drop_progress_color_cls(drop: 'TimedDrop') -> str:
    """Return the Tailwind color class for the drop's progress text."""
    if drop.is_claimed:
        return 'text-green-500'
    if drop.can_claim:
        return 'text-yellow-500'
    return ''


def _build_drop(drop: 'TimedDrop') -> Tag:
    """Build one drop as a Tag tree."""
    def _benefit(benefit) -> Tag:
        return (
            Tag('div').classes('flex flex-col items-center gap-1').add(
                Tag('div', benefit.name).classes('text-xs text-center font-medium whitespace-nowrap'),
                Tag('img').props(src=str(benefit.image_url), loading='lazy')
                          .classes('w-20 h-20 object-contain'),
            )
        )

    progress_text      = _drop_progress_text(drop)
    progress_color_cls = _drop_progress_color_cls(drop)

    return (
        Tag('div').props(id=f'drop-{drop.id}').classes('tdm-drop-card rounded p-3 flex flex-col items-center gap-1.5 min-w-0 max-w-full').add(
            Tag('div').classes('flex flex-row flex-wrap justify-center gap-2').add(
                *[_benefit(b) for b in drop.benefits]
            ),
            Tag('div', progress_text or '\u00a0')
                .props(id=f'drop-progress-{drop.id}')
                .classes('text-xs text-center whitespace-pre', progress_color_cls),
        )
    )


def _build_campaign_info(campaign: 'DropsCampaign') -> Tag:
    """Build the left-side info column (image + metadata) for a campaign."""
    # Status badge
    if campaign.active:
        status_text, status_cls = _("gui", "inventory", "status", "active"),   'text-green-500'
    elif campaign.upcoming:
        status_text, status_cls = _("gui", "inventory", "status", "upcoming"), 'text-yellow-500'
    else:
        status_text, status_cls = _("gui", "inventory", "status", "expired"),  'text-red-500'

    # Dates — shows primary date by default, secondary on hover
    date_tag = None
    try:
        starts = _("gui", "inventory", "starts").format(
            time=campaign.starts_at.astimezone().replace(microsecond=0, tzinfo=None)
        )
        ends = _("gui", "inventory", "ends").format(
            time=campaign.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
        )
        primary, secondary = (starts, ends) if campaign.upcoming else (ends, starts)
        date_tag = (
            Tag('div').classes('tdm-campaign-date text-xs text-gray-400 cursor-default').add(
                Tag('span', primary).classes('default'),
                Tag('span', secondary).classes('hovered'),
            )
        )
    except Exception:
        pass

    # Link eligibility
    link_text = _("gui", "inventory", "status", "linked" if campaign.eligible else "not_linked")
    link_cls  = 'text-green-500' if campaign.eligible else 'text-red-500'

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

    # Metadata column (right of image)
    meta_col = Tag('div').classes('flex flex-col gap-1 flex-1 min-w-0').add(
        Tag('div', campaign.name).classes('font-bold text-sm'),
        Tag('div', campaign.game.name).classes('text-xs text-gray-400'),
        Tag('div', status_text).classes('text-xs font-bold', status_cls),
    )
    if date_tag is not None:
        meta_col.add(date_tag)
    meta_col.add(
        Tag('a', link_text)
            .props(href=str(campaign.link_url), target='_blank')
            .classes('text-xs underline', link_cls),
        Tag('div', f'{_("gui", "inventory", "allowed_channels")} {acl_text}')
            .classes('text-xs text-gray-400'),
    )

    return (
        Tag('div').classes('flex flex-row grow-0 shrink basis-[400px] gap-3 items-start min-w-0').add(
            Tag('img').classes('h-36').props(src=str(campaign.image_url), loading='lazy')
                      .classes('object-cover rounded shrink-0'),
            meta_col,
        )
    )


def _build_campaign(campaign: 'DropsCampaign') -> Tag:
    """Build one campaign row as a Tag tree."""
    return (
        Tag('div').classes('tdm-campaign-card rounded p-2.5 flex flex-wrap gap-3 items-start w-full box-border').add(
            _build_campaign_info(campaign),
            Tag('div').classes('tdm-campaign-divider w-full h-px self-auto sm:w-px sm:h-auto sm:self-stretch sm:shrink-0'),
            Tag('div').classes('flex flex-wrap gap-2 flex-1 items-start').add(
                *[_build_drop(d) for d in campaign.drops]
            ),
        )
    )


def _render_campaign_html(campaign: 'DropsCampaign') -> str:
    """Render one campaign row as a complete HTML string."""
    return str(_build_campaign(campaign))


# ---------------------------------------------------------------------------
# Display rebuild
# ---------------------------------------------------------------------------

def refresh_inventory(manager: 'WebUIManager'):
    """Re-read campaigns from twitch.inventory and rebuild display."""
    manager._inventory_campaigns.clear()
    manager._campaign_html_elements.clear()

    if hasattr(manager._twitch, 'inventory') and manager._twitch.inventory:
        for campaign in manager._twitch.inventory:
            manager._inventory_campaigns[campaign.id] = campaign

    refresh_inventory_display(manager)


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
            elem = ui.html(_render_campaign_html(campaign)).classes('w-full')
            manager._campaign_html_elements[campaign.id] = elem


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_filter(manager: 'WebUIManager', key: str, value: bool):
    manager._inventory_filters[key] = value
    refresh_inventory_display(manager)


def _on_filter_change(manager: 'WebUIManager', key: str, value: bool):
    update_filter(manager, key, value)
