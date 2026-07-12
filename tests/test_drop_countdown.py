"""Verify DropSection behavior matches upstream gui.py's CampaignProgress.

Tests minute_almost_done() parity with gui.py's start_timer guard (line 750),
tick() h:mm:ss formatting and minute-subtraction branch, display() three
branches, and clear() field reset — all of which could break on upstream merge.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


@pytest.fixture
def section():
    from webui.components.main.drop_section import DropSection

    with patch("webui.components.main.drop_section.app.timer"):
        return DropSection(MagicMock())


# ---------------------------------------------------------------------------
# minute_almost_done() — parity with gui.py's start_timer guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("remaining_minutes", [0, -1])
def test_countdown_zero_remaining_immediately_done(section, remaining_minutes):
    section.display(_make_drop(remaining_minutes), countdown=True)
    assert section.minute_almost_done() is True


def test_countdown_positive_remaining_not_done(section):
    section.display(_make_drop(5), countdown=True)
    assert section.minute_almost_done() is False


@pytest.mark.parametrize("subone", [True, False])
def test_non_countdown_immediately_done(section, subone):
    section.display(_make_drop(5), countdown=False, subone=subone)
    assert section.minute_almost_done() is True


def test_stop_countdown_makes_done(section):
    section.display(_make_drop(5), countdown=True)
    assert section.minute_almost_done() is False
    section.stop_countdown()
    assert section.minute_almost_done() is True


def test_clear_makes_done(section):
    section.display(_make_drop(5), countdown=True)
    assert section.minute_almost_done() is False
    section.clear()
    assert section.minute_almost_done() is True


def test_display_none_makes_done(section):
    section.display(_make_drop(5), countdown=True)
    assert section.minute_almost_done() is False
    section.display(None)
    assert section.minute_almost_done() is True


def test_countdown_reaches_zero_becomes_done(section):
    section.display(_make_drop(5), countdown=True)
    assert section.minute_almost_done() is False
    section._countdown_start_time -= 60
    section.tick()
    assert section.minute_almost_done() is True


# ---------------------------------------------------------------------------
# tick() — h:mm:ss formatting
# ---------------------------------------------------------------------------


def test_tick_no_drop_is_noop(section):
    section.tick()
    assert section._drop_remaining_text == ""
    assert section._campaign_remaining_text == ""


def test_tick_partial_minute_subtracts_one(section):
    section.display(_make_drop(120), countdown=False, subone=False)
    section._progress_seconds = 30
    section.tick()
    assert "1:59:30" in section._drop_remaining_text


def test_tick_zero_remaining_no_subtraction(section):
    section.display(_make_drop(0), countdown=False, subone=False)
    section._progress_seconds = 30
    section.tick()
    assert "0:00:30" in section._drop_remaining_text


@pytest.mark.parametrize(
    "minutes,expected",
    [
        (0, "0:00:"),
        (59, "0:59:"),
        (60, "1:00:"),
        (600, "10:00:"),
        (125, "2:05:"),
    ],
)
def test_tick_various_minutes_format(section, minutes, expected):
    section.display(_make_drop(minutes), countdown=False, subone=False)
    assert expected in section._drop_remaining_text


def _make_campaign_drop(drop_mins: int, campaign_mins: int) -> MagicMock:
    drop = MagicMock()
    drop.remaining_minutes = drop_mins
    drop.progress = 0.5
    drop.rewards_text.return_value = "Reward"
    drop.campaign = SimpleNamespace(
        game=SimpleNamespace(name="Game"),
        name="Campaign",
        progress=0.5,
        claimed_drops=1,
        total_drops=2,
        remaining_minutes=campaign_mins,
    )
    return drop


@pytest.mark.parametrize(
    "progress_seconds,expected",
    [
        pytest.param(60, "5:00:00", id="full_minute"),
        pytest.param(45, "4:59:45", id="partial_minute"),
    ],
)
def test_tick_campaign_format(section, progress_seconds, expected):
    drop = _make_campaign_drop(drop_mins=5, campaign_mins=300)
    section.display(drop, countdown=False, subone=False)
    if progress_seconds < 60:
        section._progress_seconds = progress_seconds
        section.tick()
    assert expected in section._campaign_remaining_text


# ---------------------------------------------------------------------------
# display() — three branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "countdown,subone,active_expected,seconds_expected",
    [
        pytest.param(True, False, True, 60, id="countdown"),
        pytest.param(False, True, False, 0, id="subone"),
        pytest.param(False, False, False, 60, id="no_countdown"),
    ],
)
def test_display_branches(
    section, countdown, subone, active_expected, seconds_expected
):
    drop = _make_drop(10)
    section.display(drop, countdown=countdown, subone=subone)
    assert section._countdown_active is active_expected
    assert section._progress_seconds == seconds_expected
    assert section._current_drop is drop


def test_display_countdown_zero_remaining_falls_to_else(section):
    section.display(_make_drop(0), countdown=True)
    assert section._countdown_active is False
    assert section._progress_seconds == 60


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("_campaign_game_text", "Test Game", id="game"),
        pytest.param("_campaign_name_text", "Test Campaign", id="campaign"),
        pytest.param("_drop_rewards_text", "Test reward", id="rewards"),
    ],
)
def test_display_populates_text_fields(section, field, value):
    section.display(_make_drop(10), countdown=False)
    assert getattr(section, field) == value


def test_display_populates_progress_fields(section):
    section.display(_make_drop(10), countdown=False)
    assert section._campaign_progress_value == 0.5
    assert "50.0%" in section._campaign_percentage_text
    assert "1/2" in section._campaign_percentage_text
    assert section._drop_progress_value == 0.5
    assert "50.0%" in section._drop_percentage_text


# ---------------------------------------------------------------------------
# clear() — resets all display fields
# ---------------------------------------------------------------------------


def test_clear_resets_all_fields(section):
    section.display(_make_drop(10), countdown=False)
    assert section._campaign_game_text != "..."
    section.clear()
    assert section._current_drop is None
    assert section._campaign_game_text == "..."
    assert section._campaign_name_text == "..."
    assert section._campaign_progress_value == 0.0
    assert section._campaign_percentage_text == "-%"
    assert section._campaign_remaining_text == ""
    assert section._drop_rewards_text == "..."
    assert section._drop_progress_value == 0.0
    assert section._drop_percentage_text == "-%"
    assert section._drop_remaining_text == ""
