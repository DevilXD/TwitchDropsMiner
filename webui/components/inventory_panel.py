# Inventory panel - mirrors gui.py's InventoryOverview exactly
# Campaigns are rendered as raw HTML strings (one ui.html per campaign) to avoid
# creating hundreds of NiceGUI element objects that would overwhelm the WebSocket.

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from constants import PriorityMode
from webui.html_utils import Tag
from .base_panel import BasePanel

if TYPE_CHECKING:
    from inventory import DropsCampaign, TimedDrop
    from webui.manager import WebUIManager


class InventoryPanel(BasePanel):
    """
    Owns all mutable state for the inventory tab.

    One instance lives on WebUIManager. Each browser client calls build(),
    which registers that client's call site for _campaign_list_content.
    Filter state and campaign data are shared; .refresh() rebuilds the list
    for all connected clients at once.
    """

    def __init__(self, manager: "WebUIManager") -> None:
        super().__init__(manager)

        # Shared filter state — persists so late-joining clients start in sync.
        # Defaults match gui.py InventoryOverview.__init__:
        # not_linked = True when priority_mode is PRIORITY_ONLY, upcoming = True, rest False
        _priority_only = (
            manager._twitch.settings.priority_mode is PriorityMode.PRIORITY_ONLY
        )
        self._filter_not_linked: bool = _priority_only
        self._filter_upcoming: bool = True
        self._filter_expired: bool = False
        self._filter_excluded: bool = False
        self._filter_finished: bool = False

        self._inventory_campaigns: dict = {}  # campaign.id -> DropsCampaign

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def build(self) -> None:
        self._create_panel()

    def refresh_inventory_display(self) -> None:
        """Rebuild the campaign list for all connected clients."""
        self._campaign_list_content.refresh()

    def clear(self) -> None:
        """Clear all campaigns and rebuild the display."""
        self._inventory_campaigns.clear()
        self._campaign_list_content.refresh()

    def add_campaign(self, campaign) -> None:
        """Add or update a campaign and rebuild the display."""
        campaign_id = getattr(campaign, "id", str(id(campaign)))
        self._inventory_campaigns[campaign_id] = campaign
        self._campaign_list_content.refresh()

    def update_drop(self, drop) -> None:
        """Re-render the campaign list to reflect updated drop progress."""
        self._campaign_list_content.refresh()

    # -------------------------------------------------------------------------
    # Private — panel creation
    # -------------------------------------------------------------------------

    def _create_panel(self) -> None:
        """Build the inventory panel UI for the current NiceGUI client."""
        with ui.column().classes("w-full gap-2"):
            # Filter bar
            with ui.card().props("flat bordered").classes("w-full q-pa-xs"):
                with ui.row().classes("items-center gap-4 flex-wrap"):
                    ui.label(_("gui", "inventory", "filter", "show")).classes(
                        "text-sm font-bold"
                    )

                    for key in [
                        "not_linked",
                        "upcoming",
                        "expired",
                        "excluded",
                        "finished",
                    ]:
                        ui.checkbox(
                            _("gui", "inventory", "filter", key),
                            value=getattr(self, f"_filter_{key}"),
                            on_change=lambda e, k=key: self._on_filter_change(
                                k, e.value
                            ),
                        ).classes("text-sm").props("dense").bind_value_from(
                            self, f"_filter_{key}"
                        )

                    ui.button(
                        _("gui", "inventory", "filter", "refresh"),
                        on_click=self._refresh_inventory,
                    ).props("dense").classes("text-sm")

            # Campaign list
            self._campaign_list_content()

    # -------------------------------------------------------------------------
    # Private — refreshable content
    # -------------------------------------------------------------------------

    @ui.refreshable
    def _campaign_list_content(self) -> None:
        """Refreshable campaign list — rebuilt on any filter change or drop update."""
        # Sort matches the three stable sorts in twitch.py fetch_inventory:
        # primary: eligible first, secondary: by date, tertiary: active first
        campaigns = sorted(
            self._inventory_campaigns.values(),
            key=lambda c: (
                not c.eligible,
                c.upcoming and c.starts_at or c.ends_at,
                not c.active,
            ),
        )
        visible = [c for c in campaigns if self._campaign_visible(c)]

        with ui.column().classes("w-full gap-2"):
            if not visible:
                ui.label("No campaigns match the current filters.").classes(
                    "text-sm text-gray-500 p-4"
                )
                return
            for campaign in visible:
                ui.html(self._render_campaign_html(campaign), sanitize=False).classes(
                    "w-full"
                )

    # -------------------------------------------------------------------------
    # Private — display logic
    # -------------------------------------------------------------------------

    def _refresh_inventory(self) -> None:
        """Re-read all campaigns from twitch.inventory and rebuild the display."""
        self._inventory_campaigns.clear()

        if (
            hasattr(self._manager._twitch, "inventory")
            and self._manager._twitch.inventory
        ):
            for campaign in self._manager._twitch.inventory:
                self._inventory_campaigns[campaign.id] = campaign

        self._campaign_list_content.refresh()

    def _on_filter_change(self, key: str, value: bool) -> None:
        setattr(self, f"_filter_{key}", value)
        self._campaign_list_content.refresh()

    def _campaign_visible(self, campaign: "DropsCampaign") -> bool:
        """Exact port of InventoryOverview._update_visibility."""
        settings = self._manager._twitch.settings
        priority_only = settings.priority_mode is PriorityMode.PRIORITY_ONLY
        return (
            campaign.required_minutes > 0
            and (self._filter_not_linked or campaign.eligible)
            and (
                campaign.active
                or (self._filter_upcoming and campaign.upcoming)
                or (self._filter_expired and campaign.expired)
            )
            and (
                self._filter_excluded
                or (
                    campaign.game.name not in settings.exclude
                    and not priority_only or campaign.game.name in settings.priority
                )
            )
            and (self._filter_finished or not campaign.finished)
        )

    # -------------------------------------------------------------------------
    # Private — HTML rendering (no instance state → @staticmethod)
    # -------------------------------------------------------------------------

    @staticmethod
    def _render_campaign_html(campaign: "DropsCampaign") -> str:
        return str(InventoryPanel._build_campaign(campaign))

    @staticmethod
    def _build_campaign(campaign: "DropsCampaign") -> Tag:
        return (
            Tag("div")
            .classes(
                "rounded p-2.5 flex flex-wrap gap-3 items-start w-full box-border",
                "bg-slate-100 dark:bg-slate-700",
                "border-1 border-black/[0.12] dark:border-white/[0.28]",
            )
            .add(
                InventoryPanel._build_campaign_info(campaign),
                Tag("div").classes(
                    "w-full h-px self-auto sm:w-px sm:h-auto sm:self-stretch sm:shrink-0",
                    "bg-slate-300 dark:bg-slate-500",
                ),
                Tag("div")
                .classes("flex flex-wrap gap-2 flex-1 items-start")
                .add(*[InventoryPanel._build_drop(d) for d in campaign.drops]),
            )
        )

    @staticmethod
    def _build_campaign_info(campaign: "DropsCampaign") -> Tag:
        """Build the left-side info column (image + metadata) for a campaign."""
        # Status badge
        if campaign.active:
            status_text, status_cls = (
                _("gui", "inventory", "status", "active"),
                "text-green-500",
            )
        elif campaign.upcoming:
            status_text, status_cls = (
                _("gui", "inventory", "status", "upcoming"),
                "text-yellow-500",
            )
        else:
            status_text, status_cls = (
                _("gui", "inventory", "status", "expired"),
                "text-red-500",
            )

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
                Tag("div")
                .classes("group text-xs text-gray-400 cursor-default")
                .add(
                    Tag("span", primary).classes("inline group-hover:hidden!"),
                    Tag("span", secondary).classes("hidden group-hover:inline!"),
                )
            )
        except Exception:
            pass

        # Link eligibility
        link_text = _(
            "gui",
            "inventory",
            "status",
            "linked" if campaign.eligible else "not_linked",
        )
        link_cls = "text-green-500" if campaign.eligible else "text-red-500"

        # Allowed channels
        acl = campaign.allowed_channels
        if acl:
            names = [ch.name for ch in acl]
            if len(names) <= 5:
                acl_text = ", ".join(names)
            else:
                acl_text = (
                    ", ".join(names[:4])
                    + ", "
                    + _("gui", "inventory", "and_more").format(amount=len(acl) - 4)
                )
        else:
            acl_text = _("gui", "inventory", "all_channels")

        # Metadata column (right of image)
        meta_col = (
            Tag("div")
            .classes("flex flex-col gap-1 flex-1 min-w-0")
            .add(
                Tag("div", campaign.name).classes("font-bold text-sm"),
                Tag("div", campaign.game.name).classes("text-xs text-gray-400"),
                Tag("div", status_text).classes("text-xs", status_cls),
            )
        )
        if date_tag is not None:
            meta_col.add(date_tag)
        meta_col.add(
            Tag("a", link_text)
            .props(
                href=str(campaign.link_url), target="_blank", rel="noopener noreferrer"
            )
            .classes("text-xs", link_cls),
            Tag(
                "div", f"{_('gui', 'inventory', 'allowed_channels')} {acl_text}"
            ).classes("text-xs text-gray-400"),
        )

        return (
            Tag("div")
            .classes(
                "flex flex-row grow-0 shrink basis-[400px] gap-3 items-start min-w-0"
            )
            .add(
                Tag("img")
                .classes("h-36")
                .props(src=str(campaign.image_url), loading="lazy")
                .classes("object-cover rounded shrink-0"),
                meta_col,
            )
        )

    @staticmethod
    def _build_drop(drop: "TimedDrop") -> Tag:
        def _benefit(benefit) -> Tag:
            return (
                Tag("div")
                .classes("flex flex-col items-center gap-1")
                .add(
                    Tag("div", benefit.name).classes(
                        "text-xs text-center font-medium whitespace-nowrap"
                    ),
                    Tag("img")
                    .props(src=str(benefit.image_url), loading="lazy")
                    .classes("w-20 h-20 object-contain"),
                )
            )

        progress_text = InventoryPanel._drop_progress_text(drop)
        progress_color_cls = InventoryPanel._drop_progress_color_cls(drop)

        return (
            Tag("div")
            .props(id=f"drop-{drop.id}")
            .classes(
                "rounded p-3 flex flex-col items-center gap-1.5 min-w-0 max-w-full",
                "bg-slate-200 dark:bg-slate-800",
                "border-1 border-black/[0.12] dark:border-white/[0.28]",
            )
            .add(
                Tag("div")
                .classes("flex flex-row flex-wrap justify-center gap-2")
                .add(*[_benefit(b) for b in drop.benefits]),
                Tag("div", progress_text or "\u00a0")
                .props(id=f"drop-progress-{drop.id}")
                .classes("text-xs text-center whitespace-pre", progress_color_cls),
            )
        )

    @staticmethod
    def _fmt_datetime(dt: datetime) -> str:
        """Remove microseconds and timezone info for display."""
        return (
            dt.astimezone()
            .replace(microsecond=0, tzinfo=None)
            .strftime("%Y-%m-%d %H:%M:%S")
        )

    @staticmethod
    def _drop_progress_text(drop: "TimedDrop") -> str:
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
    def _drop_progress_color_cls(drop: "TimedDrop") -> str:
        """Return the Tailwind color class for the drop's progress text."""
        if drop.is_claimed:
            return "text-green-500"
        if drop.can_claim:
            return "text-yellow-500"
        return ""
