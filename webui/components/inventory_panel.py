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
from .base_panel import BasePanel

if TYPE_CHECKING:
    from inventory import DropsCampaign, TimedDrop
    from webui.manager import WebUIManager


class InventoryPanel(BasePanel):
    """
    Owns all widget references and mutable state for the inventory tab.

    All UI state lives on this object. Each browser tab that connects gets its
    own set of widget refs (container + checkboxes) registered via _add_client /
    _remove_client. Filter state and campaign data are shared across all clients
    so every tab always shows the same view.
    """

    def __init__(self, manager: 'WebUIManager') -> None:
        super().__init__(manager)

        # Shared filter state — persists so late-joining clients start in sync.
        # Defaults match gui.py InventoryOverview.__init__:
        # not_linked = True when priority_mode is PRIORITY_ONLY, upcoming = True, rest False
        _priority_only = manager._twitch.settings.priority_mode is PriorityMode.PRIORITY_ONLY
        self._inventory_filters: dict = {
            "not_linked": _priority_only,
            "upcoming":   True,
            "expired":    False,
            "excluded":   False,
            "finished":   False,
        }
        self._inventory_campaigns: dict = {}   # campaign.id -> DropsCampaign

        # Per-client widget refs: client_id -> {container, checkboxes}
        self._client_data: dict = {}
        # campaign.id -> {client_id -> ui.html element}
        self._campaign_html_elements: dict = {}

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def build(self) -> None:
        self._create_panel()

    def refresh_inventory_display(self) -> None:
        """Rebuild the campaign list for all connected clients."""
        for client_id in list(self._client_data.keys()):
            self._rebuild_client_container(client_id)

    def clear(self) -> None:
        """Clear all campaigns and rebuild the display."""
        self._inventory_campaigns.clear()
        self._campaign_html_elements.clear()
        self.refresh_inventory_display()

    def add_campaign(self, campaign) -> None:
        """Add or update a campaign and rebuild the display."""
        campaign_id = getattr(campaign, 'id', str(id(campaign)))
        self._inventory_campaigns[campaign_id] = campaign
        self.refresh_inventory_display()

    def update_drop(self, drop) -> None:
        """
        Re-render one campaign's HTML on every connected client.

        _campaign_html_elements maps campaign.id -> {client_id -> ui.html}.
        Each ui.html element knows its own client, so assigning .content pushes
        the update to the right browser tab automatically.
        """
        html = self._render_campaign_html(drop.campaign)
        for elem in self._campaign_html_elements.get(drop.campaign.id, {}).values():
            elem.content = html

    # -------------------------------------------------------------------------
    # Private — client lifecycle
    # -------------------------------------------------------------------------

    def _add_client(self, client_id: str, container, checkboxes: dict) -> None:
        self._client_data[client_id] = {'container': container, 'checkboxes': checkboxes}

    def _remove_client(self, client_id: str) -> None:
        self._client_data.pop(client_id, None)
        for elem_map in self._campaign_html_elements.values():
            elem_map.pop(client_id, None)

    # -------------------------------------------------------------------------
    # Private — panel creation
    # -------------------------------------------------------------------------

    def _create_panel(self) -> None:
        """Build the inventory panel UI for the current NiceGUI client."""
        if not NICEGUI_AVAILABLE:
            return

        client_id: str = ui.context.client.id

        with ui.column().classes('w-full gap-2'):

            # Filter bar
            with ui.card().props('flat bordered').classes('w-full q-pa-xs'):
                with ui.row().classes('items-center gap-4 flex-wrap'):
                    ui.label(_("gui", "inventory", "filter", "show")).classes('text-sm font-bold')

                    checkboxes: dict = {}
                    for key in ["not_linked", "upcoming", "expired", "excluded", "finished"]:
                        cb = ui.checkbox(
                            _("gui", "inventory", "filter", key),
                            value=self._inventory_filters[key],
                            on_change=lambda e, k=key: self._on_filter_change(k, e.value),
                        ).classes('text-sm').props('dense')
                        checkboxes[key] = cb

                    ui.button(
                        _("gui", "inventory", "filter", "refresh"),
                        on_click=lambda: self._refresh_inventory(),
                    ).props('dense').classes('text-sm')

            # Campaign list — uses browser scroll, no inner scroll area
            container = ui.column().classes('w-full gap-3')
            with container:
                ui.label("Loading inventory...").classes('text-sm text-gray-500')

        self._add_client(client_id, container, checkboxes)
        ui.context.client.on_disconnect(lambda: self._remove_client(client_id))

        # Populate with any campaigns already collected before this client connected
        self._rebuild_client_container(client_id)

    # -------------------------------------------------------------------------
    # Private — display logic
    # -------------------------------------------------------------------------

    def _refresh_inventory(self) -> None:
        """Re-read all campaigns from twitch.inventory and rebuild the display."""
        self._inventory_campaigns.clear()
        self._campaign_html_elements.clear()

        if hasattr(self._manager._twitch, 'inventory') and self._manager._twitch.inventory:
            for campaign in self._manager._twitch.inventory:
                self._inventory_campaigns[campaign.id] = campaign

        self.refresh_inventory_display()

    def _rebuild_client_container(self, client_id: str) -> None:
        """Rebuild the campaign list for one client's container."""
        data = self._client_data.get(client_id)
        if data is None:
            return
        container = data['container']

        # Sort matches the three stable sorts in twitch.py fetch_inventory:
        # primary: eligible first, secondary: by date, tertiary: active first
        campaigns = sorted(
            self._inventory_campaigns.values(),
            key=lambda c: (not c.eligible, c.upcoming and c.starts_at or c.ends_at, not c.active),
        )
        visible = [c for c in campaigns if self._campaign_visible(c)]

        # Remove stale element refs for this client before rebuilding
        for elem_map in self._campaign_html_elements.values():
            elem_map.pop(client_id, None)

        container.clear()
        with container:
            if not visible:
                ui.label("No campaigns match the current filters.").classes(
                    'text-sm text-gray-500 p-4'
                )
                return

            for campaign in visible:
                elem = ui.html(
                    self._render_campaign_html(campaign),
                    sanitize=False
                ).classes('w-full')
                self._campaign_html_elements.setdefault(campaign.id, {})[client_id] = elem

    def _on_filter_change(self, key: str, value: bool) -> None:
        self._inventory_filters[key] = value
        # Push the new checkbox state to every connected client
        for data in self._client_data.values():
            cb = data['checkboxes'].get(key)
            if cb is not None:
                cb.set_value(value)
        self.refresh_inventory_display()

    def _campaign_visible(self, campaign: 'DropsCampaign') -> bool:
        """Exact port of InventoryOverview._update_visibility."""
        f = self._inventory_filters
        settings = self._manager._twitch.settings
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

    # -------------------------------------------------------------------------
    # Private — HTML rendering (no instance state → @staticmethod)
    # -------------------------------------------------------------------------

    @staticmethod
    def _render_campaign_html(campaign: 'DropsCampaign') -> str:
        return str(InventoryPanel._build_campaign(campaign))

    @staticmethod
    def _build_campaign(campaign: 'DropsCampaign') -> Tag:
        return (
            Tag('div').classes('tdm-campaign-card rounded p-2.5 flex flex-wrap gap-3 items-start w-full box-border').add(
                InventoryPanel._build_campaign_info(campaign),
                Tag('div').classes('tdm-campaign-divider w-full h-px self-auto sm:w-px sm:h-auto sm:self-stretch sm:shrink-0'),
                Tag('div').classes('flex flex-wrap gap-2 flex-1 items-start').add(
                    *[InventoryPanel._build_drop(d) for d in campaign.drops]
                ),
            )
        )

    @staticmethod
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
                time=InventoryPanel._fmt_datetime(campaign.starts_at)
            )
            ends = _("gui", "inventory", "ends").format(
                time=InventoryPanel._fmt_datetime(campaign.ends_at)
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
            Tag('div', status_text).classes('text-xs', status_cls),
        )
        if date_tag is not None:
            meta_col.add(date_tag)
        meta_col.add(
            Tag('a', link_text)
                .props(href=str(campaign.link_url), target='_blank', rel='noopener noreferrer')
                .classes('text-xs', link_cls),
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

    @staticmethod
    def _build_drop(drop: 'TimedDrop') -> Tag:
        def _benefit(benefit) -> Tag:
            return (
                Tag('div').classes('flex flex-col items-center gap-1').add(
                    Tag('div', benefit.name).classes('text-xs text-center font-medium whitespace-nowrap'),
                    Tag('img').props(src=str(benefit.image_url), loading='lazy')
                              .classes('w-20 h-20 object-contain'),
                )
            )

        progress_text      = InventoryPanel._drop_progress_text(drop)
        progress_color_cls = InventoryPanel._drop_progress_color_cls(drop)

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

    @staticmethod
    def _fmt_datetime(dt: datetime) -> datetime:
        """Remove microseconds and timezone info for display."""
        return dt.astimezone().replace(microsecond=0, tzinfo=None)

    @staticmethod
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
                    time=InventoryPanel._fmt_datetime(drop.ends_at)
                )
            return text
        if drop.required_minutes > 0:
            text = _("gui", "inventory", "minutes_progress").format(
                minutes=drop.required_minutes
            )
        else:
            text = ""
        now = datetime.now(timezone.utc)
        if now < drop.starts_at and drop.starts_at > drop.campaign.starts_at:
            text += "\n" + _("gui", "inventory", "starts").format(
                time=InventoryPanel._fmt_datetime(drop.starts_at)
            )
        elif drop.ends_at < drop.campaign.ends_at:
            text += "\n" + _("gui", "inventory", "ends").format(
                time=InventoryPanel._fmt_datetime(drop.ends_at)
            )
        return text

    @staticmethod
    def _drop_progress_color_cls(drop: 'TimedDrop') -> str:
        """Return the Tailwind color class for the drop's progress text."""
        if drop.is_claimed:
            return 'text-green-500'
        if drop.can_claim:
            return 'text-yellow-500'
        return ''
