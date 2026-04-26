from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from nicegui import ui

from translate import _

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class DropSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager

        self._current_drop = None
        self._countdown_active: bool = False
        self._progress_seconds: int = 0
        self._countdown_start_time: float | None = None

        self._campaign_game_text: str = "..."
        self._campaign_name_text: str = "..."
        self._campaign_progress_value: float = 0.0
        self._campaign_percentage_text: str = "-%"
        self._campaign_remaining_text: str = ""
        self._drop_rewards_text: str = "..."
        self._drop_progress_value: float = 0.0
        self._drop_percentage_text: str = "-%"
        self._drop_remaining_text: str = ""

    def build(self) -> None:
        with ui.card().props("flat bordered").classes("w-full gap-1"):
            ui.label(_("gui", "progress", "name")).classes("font-bold text-sm mb-1")
            with ui.grid(columns=2).classes("w-full text-xs gap-1"):
                ui.label(_("gui", "progress", "game")).classes("font-bold")
                ui.label(_("gui", "progress", "campaign")).classes("font-bold")
                ui.label().bind_text_from(self, "_campaign_game_text")
                ui.label().bind_text_from(self, "_campaign_name_text")
            ui.label(_("gui", "progress", "campaign_progress")).classes(
                "text-xs font-bold"
            )
            with ui.row().classes("w-full gap-2 items-center text-xs"):
                ui.label().classes("w-24").bind_text_from(
                    self, "_campaign_percentage_text"
                )
                ui.label().classes("flex-1").bind_text_from(
                    self, "_campaign_remaining_text"
                )
            ui.linear_progress(value=0, show_value=False).classes(
                "w-full h-4"
            ).bind_value_from(self, "_campaign_progress_value")
            ui.separator().classes("my-1")
            ui.label(_("gui", "progress", "drop")).classes("text-xs font-bold")
            ui.label().classes("text-xs").bind_text_from(self, "_drop_rewards_text")
            ui.label(_("gui", "progress", "drop_progress")).classes("text-xs font-bold")
            with ui.row().classes("w-full gap-2 items-center text-xs"):
                ui.label().classes("w-24").bind_text_from(self, "_drop_percentage_text")
                ui.label().classes("flex-1").bind_text_from(
                    self, "_drop_remaining_text"
                )
            ui.linear_progress(value=0, show_value=False).classes(
                "w-full h-4"
            ).bind_value_from(self, "_drop_progress_value")

        timer = ui.timer(1.0, self.tick)
        ui.context.client.on_disconnect(lambda: timer.cancel())

    def display(self, drop, *, countdown: bool = True, subone: bool = False) -> None:
        if drop is None:
            self.clear()
            return
        self._current_drop = drop
        if countdown:
            self._countdown_active = True
            self._countdown_start_time = monotonic()
            self._progress_seconds = 60
        elif subone:
            self._countdown_active = False
            self._countdown_start_time = None
            self._progress_seconds = 0
        else:
            self._countdown_active = False
            self._countdown_start_time = None
            self._progress_seconds = 60
        self._do_display(drop)
        self.tick()

    def clear(self) -> None:
        self._current_drop = None
        self._countdown_active = False
        self._countdown_start_time = None
        self._progress_seconds = 0
        self._do_clear()

    def tick(self) -> None:
        drop = self._current_drop
        if drop is None:
            return
        if self._countdown_active and self._countdown_start_time is not None:
            elapsed = int(monotonic() - self._countdown_start_time)
            self._progress_seconds = max(0, 60 - elapsed)
        secs = self._progress_seconds % 60

        drop_mins = drop.remaining_minutes
        if self._progress_seconds < 60 and drop_mins > 0:
            drop_mins -= 1
        h, m = divmod(drop_mins, 60)
        self._drop_remaining_text = _("gui", "progress", "remaining").format(
            time=f"{h:>2}:{m:02}:{secs:02}"
        )

        camp_mins = drop.campaign.remaining_minutes
        if self._progress_seconds < 60 and camp_mins > 0:
            camp_mins -= 1
        h, m = divmod(camp_mins, 60)
        self._campaign_remaining_text = _("gui", "progress", "remaining").format(
            time=f"{h:>2}:{m:02}:{secs:02}"
        )

    def _do_display(self, drop) -> None:
        campaign = drop.campaign
        self._campaign_game_text = campaign.game.name
        self._campaign_name_text = campaign.name
        self._campaign_progress_value = campaign.progress
        self._campaign_percentage_text = f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
        self._drop_rewards_text = drop.rewards_text()
        self._drop_progress_value = drop.progress
        self._drop_percentage_text = f"{drop.progress:6.1%}"

    def _do_clear(self) -> None:
        self._campaign_game_text = "..."
        self._campaign_name_text = "..."
        self._campaign_progress_value = 0.0
        self._campaign_percentage_text = "-%"
        self._campaign_remaining_text = ""
        self._drop_rewards_text = "..."
        self._drop_progress_value = 0.0
        self._drop_percentage_text = "-%"
        self._drop_remaining_text = ""
