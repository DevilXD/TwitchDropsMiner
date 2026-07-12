"""Verify DropSection countdown behavior matches upstream gui.py CampaignProgress.

gui.py's CampaignProgress requires tkinter widgets so it can't be imported
headless. Instead we test the behavioral contract: minute_almost_done() must
return True immediately when countdown=True but remaining_minutes <= 0,
matching gui.py's start_timer guard (line 750).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest


def _make_drop(remaining_minutes: int) -> MagicMock:
    drop = MagicMock()
    drop.remaining_minutes = remaining_minutes
    drop.progress = 0.5
    drop.rewards_text.return_value = "Test reward"
    drop.campaign = SimpleNamespace(
        game=SimpleNamespace(name="Test Game"),
        name="Test Campaign",
        progress=0.5,
        claimed_drops=1,
        total_drops=2,
        remaining_minutes=remaining_minutes,
    )
    return drop


def _make_section() -> "DropSection":
    from webui.components.main.drop_section import DropSection

    with patch("webui.components.main.drop_section.app.timer"):
        manager = MagicMock()
        return DropSection(manager)


class TestDropCountdown:
    @pytest.mark.parametrize("remaining_minutes", [0, -1])
    def test_countdown_zero_remaining_immediately_done(self, remaining_minutes):
        # gui.py start_timer: remaining_minutes <= 0 → no timer task → minute_almost_done() is True
        section = _make_section()
        drop = _make_drop(remaining_minutes)
        section.display(drop, countdown=True)
        assert section.minute_almost_done() is True

    def test_countdown_positive_remaining_not_done(self):
        # gui.py start_timer: remaining_minutes > 0 → timer task created → minute_almost_done() is False
        section = _make_section()
        drop = _make_drop(5)
        section.display(drop, countdown=True)
        assert section.minute_almost_done() is False

    def test_subone_immediately_done(self):
        section = _make_section()
        drop = _make_drop(5)
        section.display(drop, countdown=False, subone=True)
        assert section.minute_almost_done() is True

    def test_no_countdown_no_subone_immediately_done(self):
        section = _make_section()
        drop = _make_drop(5)
        section.display(drop, countdown=False, subone=False)
        assert section.minute_almost_done() is True

    def test_stop_countdown_makes_done(self):
        section = _make_section()
        drop = _make_drop(5)
        section.display(drop, countdown=True)
        assert section.minute_almost_done() is False
        section.stop_countdown()
        assert section.minute_almost_done() is True

    def test_clear_makes_done(self):
        section = _make_section()
        drop = _make_drop(5)
        section.display(drop, countdown=True)
        assert section.minute_almost_done() is False
        section.clear()
        assert section.minute_almost_done() is True

    def test_display_none_makes_done(self):
        section = _make_section()
        drop = _make_drop(5)
        section.display(drop, countdown=True)
        assert section.minute_almost_done() is False
        section.display(None)
        assert section.minute_almost_done() is True

    def test_countdown_reaches_zero_becomes_done(self):
        section = _make_section()
        drop = _make_drop(5)
        section.display(drop, countdown=True)
        assert section.minute_almost_done() is False
        # Simulate 60 seconds elapsing
        section._countdown_start_time -= 60
        section.tick()
        assert section.minute_almost_done() is True
