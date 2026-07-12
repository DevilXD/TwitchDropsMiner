"""Verify InventoryPanel logic matches upstream gui.py's InventoryOverview.

Tests _campaign_visible filter parity, _drop_progress_text branch coverage,
_drop_progress_color_cls precedence, _fmt_datetime timezone stripping, and
_render_campaign_html output including XSS escaping — all of which could
break on upstream merge.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from constants import PriorityMode
from webui.components.inventory_panel import InventoryPanel

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    priority_mode: PriorityMode = PriorityMode.ENDING_SOONEST,
    exclude: set[str] | None = None,
    priority: list[str] | None = None,
):
    settings = MagicMock()
    settings.priority_mode = priority_mode
    settings.exclude = exclude or set()
    settings.priority = priority or []
    settings.enable_badges_emotes = False
    return settings


def _make_twitch(settings=None):
    twitch = MagicMock()
    twitch.settings = settings or _make_settings()
    twitch.inventory = []
    return twitch


def _make_manager(twitch=None):
    manager = MagicMock()
    manager._twitch = twitch or _make_twitch()
    return manager


def _make_campaign(
    *,
    name: str = "Test Campaign",
    game_name: str = "Test Game",
    required_minutes: int = 240,
    eligible: bool = True,
    active: bool = True,
    upcoming: bool = False,
    expired: bool = False,
    finished: bool = False,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    link_url: str = "https://example.com/link",
    image_url: str = "https://example.com/image.jpg",
    allowed_channels: list | None = None,
    drops: list | None = None,
    claimed_drops: int = 0,
    total_drops: int = 1,
    progress: float = 0.5,
):
    return SimpleNamespace(
        name=name,
        game=SimpleNamespace(name=game_name),
        required_minutes=required_minutes,
        eligible=eligible,
        active=active,
        upcoming=upcoming,
        expired=expired,
        finished=finished,
        starts_at=starts_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
        ends_at=ends_at or datetime(2024, 12, 31, tzinfo=timezone.utc),
        link_url=link_url,
        image_url=image_url,
        allowed_channels=allowed_channels or [],
        drops=drops or [],
        claimed_drops=claimed_drops,
        total_drops=total_drops,
        progress=progress,
    )


def _make_drop(
    *,
    id: str = "drop-1",
    is_claimed: bool = False,
    can_claim: bool = False,
    current_minutes: int = 0,
    can_earn: bool = False,
    progress: float = 0.0,
    required_minutes: int = 240,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    campaign=None,
    benefits: list | None = None,
):
    if campaign is None:
        campaign = _make_campaign()
    return SimpleNamespace(
        id=id,
        is_claimed=is_claimed,
        can_claim=can_claim,
        current_minutes=current_minutes,
        can_earn=lambda *a, **kw: can_earn,
        progress=progress,
        required_minutes=required_minutes,
        starts_at=starts_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
        ends_at=ends_at or datetime(2024, 12, 31, tzinfo=timezone.utc),
        campaign=campaign,
        benefits=benefits
        or [
            SimpleNamespace(name="Reward", image_url="https://example.com/benefit.png")
        ],
    )


def _make_panel(
    *,
    filter_not_linked: bool = False,
    filter_upcoming: bool = True,
    filter_expired: bool = False,
    filter_excluded: bool = False,
    filter_finished: bool = False,
    settings=None,
):
    settings = settings or _make_settings()
    twitch = _make_twitch(settings)
    manager = _make_manager(twitch)
    panel = InventoryPanel(manager)
    panel._filter_not_linked = filter_not_linked
    panel._filter_upcoming = filter_upcoming
    panel._filter_expired = filter_expired
    panel._filter_excluded = filter_excluded
    panel._filter_finished = filter_finished
    return panel


# ---------------------------------------------------------------------------
# _campaign_visible
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "panel_kwargs,campaign_kwargs,expected",
    [
        pytest.param({}, {"active": True}, True, id="active_visible"),
        pytest.param(
            {}, {"required_minutes": 0, "active": True}, False, id="zero_minutes_hidden"
        ),
        pytest.param(
            {"filter_not_linked": False},
            {"eligible": False, "active": True},
            False,
            id="not_linked_hidden",
        ),
        pytest.param(
            {"filter_not_linked": True},
            {"eligible": False, "active": True},
            True,
            id="not_linked_visible",
        ),
        pytest.param(
            {"filter_upcoming": True},
            {"active": False, "upcoming": True},
            True,
            id="upcoming_visible",
        ),
        pytest.param(
            {"filter_upcoming": False},
            {"active": False, "upcoming": True},
            False,
            id="upcoming_hidden",
        ),
        pytest.param(
            {"filter_expired": True},
            {"active": False, "expired": True},
            True,
            id="expired_visible",
        ),
        pytest.param(
            {"filter_expired": False},
            {"active": False, "expired": True},
            False,
            id="expired_hidden",
        ),
        pytest.param(
            {"filter_finished": False},
            {"active": True, "finished": True},
            False,
            id="finished_hidden",
        ),
        pytest.param(
            {"filter_finished": True},
            {"active": True, "finished": True},
            True,
            id="finished_visible",
        ),
        pytest.param(
            {
                "filter_not_linked": True,
                "filter_upcoming": True,
                "filter_expired": True,
                "filter_excluded": True,
                "filter_finished": True,
            },
            {
                "eligible": False,
                "active": False,
                "expired": True,
                "finished": True,
                "required_minutes": 10,
            },
            True,
            id="all_filters_pass",
        ),
    ],
)
def test_campaign_visible(panel_kwargs, campaign_kwargs, expected):
    panel = _make_panel(**panel_kwargs)
    assert panel._campaign_visible(_make_campaign(**campaign_kwargs)) is expected


@pytest.mark.parametrize(
    "filter_excluded,expected",
    [
        pytest.param(False, False, id="excluded_hidden"),
        pytest.param(True, True, id="excluded_visible_when_filter"),
    ],
)
def test_excluded_game(filter_excluded, expected):
    panel = _make_panel(filter_excluded=filter_excluded)
    panel._manager._twitch.settings.exclude = {"Excluded Game"}
    assert (
        panel._campaign_visible(_make_campaign(game_name="Excluded Game", active=True))
        is expected
    )


def test_priority_game_visible_even_if_excluded():
    panel = _make_panel()
    panel._manager._twitch.settings.exclude = {"Priority Game"}
    panel._manager._twitch.settings.priority = ["Priority Game"]
    assert (
        panel._campaign_visible(_make_campaign(game_name="Priority Game", active=True))
        is True
    )


@pytest.mark.parametrize(
    "game_name,priority,expected",
    [
        pytest.param(
            "Regular Game", [], False, id="non_priority_hidden_in_priority_only"
        ),
        pytest.param(
            "Priority Game",
            ["Priority Game"],
            True,
            id="priority_visible_in_priority_only",
        ),
    ],
)
def test_priority_only_mode(game_name, priority, expected):
    panel = _make_panel()
    panel._manager._twitch.settings.priority_mode = PriorityMode.PRIORITY_ONLY
    panel._manager._twitch.settings.priority = priority
    assert (
        panel._campaign_visible(_make_campaign(game_name=game_name, active=True))
        is expected
    )


# ---------------------------------------------------------------------------
# _drop_progress_text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "drop_kwargs,assertions",
    [
        pytest.param(
            {"is_claimed": True}, lambda r: "claimed" in r.lower(), id="claimed"
        ),
        pytest.param(
            {"can_claim": True},
            lambda r: "ready" in r.lower() or "claim" in r.lower(),
            id="can_claim",
        ),
        pytest.param(
            {
                "current_minutes": 120,
                "can_earn": True,
                "progress": 0.5,
                "required_minutes": 240,
            },
            lambda r: "50.0%" in r and "240" in r,
            id="can_earn_with_progress",
        ),
        pytest.param(
            {
                "current_minutes": 60,
                "can_earn": False,
                "progress": 0.25,
                "required_minutes": 240,
            },
            lambda r: "25.0%" in r and "240" in r,
            id="current_minutes_without_can_earn",
        ),
        pytest.param(
            {"current_minutes": 0, "can_earn": False, "required_minutes": 240},
            lambda r: "240" in r,
            id="required_minutes_only",
        ),
        pytest.param(
            {"required_minutes": 0, "can_earn": False, "current_minutes": 0},
            lambda r: "0" not in r or r == "",
            id="zero_required_minutes",
        ),
    ],
)
def test_drop_progress_text(drop_kwargs, assertions):
    drop = _make_drop(**drop_kwargs)
    result = InventoryPanel._drop_progress_text(drop)
    assert assertions(result)


def test_drop_ends_before_campaign_shows_end_date():
    campaign = _make_campaign(
        starts_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ends_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
    )
    drop = _make_drop(
        can_earn=False,
        current_minutes=0,
        required_minutes=240,
        starts_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ends_at=datetime(2024, 6, 30, tzinfo=timezone.utc),
        campaign=campaign,
    )
    assert "2024" in InventoryPanel._drop_progress_text(drop)


def test_drop_starts_after_campaign_shows_start_date():
    future = datetime.now(timezone.utc) + timedelta(days=30)
    campaign = _make_campaign(
        starts_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ends_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
    )
    drop = _make_drop(
        can_earn=False,
        current_minutes=0,
        required_minutes=240,
        starts_at=future,
        ends_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
        campaign=campaign,
    )
    result = InventoryPanel._drop_progress_text(drop)
    assert "2024" in result or str(future.year) in result


# ---------------------------------------------------------------------------
# _drop_progress_color_cls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "drop_kwargs,expected",
    [
        pytest.param({"is_claimed": True}, "text-green-500", id="claimed"),
        pytest.param({"can_claim": True}, "text-yellow-500", id="can_claim"),
        pytest.param({}, "", id="in_progress"),
        pytest.param(
            {"is_claimed": True, "can_claim": True},
            "text-green-500",
            id="claimed_overrides_can_claim",
        ),
    ],
)
def test_drop_progress_color_cls(drop_kwargs, expected):
    assert (
        InventoryPanel._drop_progress_color_cls(_make_drop(**drop_kwargs)) == expected
    )


# ---------------------------------------------------------------------------
# _fmt_datetime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dt,assertions",
    [
        pytest.param(
            datetime(2024, 6, 15, 12, 30, 45, 123456, tzinfo=timezone.utc),
            lambda r: "123456" not in r and "2024-06-15" in r and "30:45" in r,
            id="strips_microseconds",
        ),
        pytest.param(
            datetime(2024, 6, 15, 12, 30, 0, tzinfo=timezone.utc),
            lambda r: "UTC" not in r and "Z" not in r,
            id="strips_timezone",
        ),
        pytest.param(
            datetime(2024, 6, 15, 12, 30, 0),
            lambda r: "2024-06-15" in r,
            id="naive_datetime",
        ),
    ],
)
def test_fmt_datetime(dt, assertions):
    assert assertions(InventoryPanel._fmt_datetime(dt))


# ---------------------------------------------------------------------------
# _render_campaign_html
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "campaign_kwargs,substring",
    [
        pytest.param({"name": "My Campaign"}, "My Campaign", id="campaign_name"),
        pytest.param({"game_name": "Cool Game"}, "Cool Game", id="game_name"),
        pytest.param(
            {"image_url": "https://example.com/img.jpg"},
            "https://example.com/img.jpg",
            id="image_url",
        ),
        pytest.param(
            {"link_url": "https://example.com/link"},
            "https://example.com/link",
            id="link_url",
        ),
    ],
)
def test_html_contains_text(campaign_kwargs, substring):
    html = InventoryPanel._render_campaign_html(
        _make_campaign(**campaign_kwargs, drops=[])
    )
    assert substring in html


@pytest.mark.parametrize(
    "field,value,expected",
    [
        pytest.param(
            "name",
            "<script>alert(1)</script>",
            "&lt;script&gt;",
            id="escapes_campaign_name",
        ),
        pytest.param(
            "game_name",
            "<img src=x onerror=alert(1)>",
            "&lt;img",
            id="escapes_game_name",
        ),
    ],
)
def test_html_escapes_user_input(field, value, expected):
    html = InventoryPanel._render_campaign_html(
        _make_campaign(**{field: value}, drops=[])
    )
    assert value not in html
    assert expected in html


def test_html_contains_drop_benefit_name():
    benefit = SimpleNamespace(
        name="Cool Badge", image_url="https://example.com/badge.png"
    )
    drop = _make_drop(id="d1", benefits=[benefit])
    html = InventoryPanel._render_campaign_html(_make_campaign(drops=[drop]))
    assert "Cool Badge" in html
    assert "https://example.com/badge.png" in html


def test_html_contains_drop_id():
    drop = _make_drop(id="my-drop-id")
    html = InventoryPanel._render_campaign_html(_make_campaign(drops=[drop]))
    assert 'id="drop-my-drop-id"' in html
    assert 'id="drop-progress-my-drop-id"' in html


@pytest.mark.parametrize(
    "campaign_kwargs,color_cls",
    [
        pytest.param({"active": True}, "text-green-500", id="active"),
        pytest.param(
            {"active": False, "upcoming": True}, "text-yellow-500", id="upcoming"
        ),
        pytest.param({"active": False, "expired": True}, "text-red-500", id="expired"),
    ],
)
def test_html_status_color(campaign_kwargs, color_cls):
    html = InventoryPanel._render_campaign_html(
        _make_campaign(**campaign_kwargs, drops=[])
    )
    assert color_cls in html


def test_allowed_channels_listed():
    c = _make_campaign(
        allowed_channels=[
            SimpleNamespace(name="ChannelA"),
            SimpleNamespace(name="ChannelB"),
        ],
        drops=[],
    )
    html = InventoryPanel._render_campaign_html(c)
    assert "ChannelA" in html
    assert "ChannelB" in html


def test_many_channels_truncated():
    channels = [SimpleNamespace(name=f"Ch{i}") for i in range(10)]
    html = InventoryPanel._render_campaign_html(
        _make_campaign(allowed_channels=channels, drops=[])
    )
    assert "Ch0" in html
    assert "Ch4" not in html


def test_no_channels_shows_all_channels():
    html = InventoryPanel._render_campaign_html(
        _make_campaign(allowed_channels=[], drops=[])
    )
    assert len(html) > 0
