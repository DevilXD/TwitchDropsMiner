from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from constants import MAX_EXTRA_MINUTES, State
from inventory import (
    CAMPAIGN_IMAGE_SIZE,
    CampaignStatus,
    DropStatus,
    DropsCampaign,
    campaign_image_url,
)


class FakeInvGUI:
    def __init__(self) -> None:
        self.updates = []

    def update_drop(self, drop) -> None:
        self.updates.append(drop)


class FakeGUI:
    def __init__(self) -> None:
        self.inv = FakeInvGUI()


class FakeSettings:
    enable_badges_emotes = False


class FakeTwitch:
    def __init__(self) -> None:
        self.gui = FakeGUI()
        self.settings = FakeSettings()
        self.prints = []
        self.changes = []

    def print(self, message: str) -> None:
        self.prints.append(message)

    def change_state(self, state: State, *, reason: str = "") -> None:
        self.changes.append((state, reason))

    def request_state(self, state: State, *, reason: str = "") -> None:
        self.changes.append((state, reason))


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def campaign_data(
    *,
    start_offset: int = -3600,
    end_offset: int = 3600,
    status: str = "ACTIVE",
    drops: int = 1,
    linked: bool = True,
) -> dict:
    now = datetime.now(timezone.utc)
    starts_at = iso(now + timedelta(seconds=start_offset))
    ends_at = iso(now + timedelta(seconds=end_offset))
    return {
        "id": "campaign-1",
        "name": "Test Campaign",
        "game": {
            "id": 10,
            "name": "game",
            "displayName": "Game",
            "boxArtURL": "https://static-cdn.jtvnw.net/ttv-boxart/10-285x380.jpg",
        },
        "self": {"isAccountConnected": linked},
        "accountLinkURL": "https://example.com/link",
        "startAt": starts_at,
        "endAt": ends_at,
        "status": status,
        "allow": {"channels": [], "isEnabled": True},
        "timeBasedDrops": [
            {
                "id": f"drop-{index}",
                "name": f"Drop {index}",
                "benefitEdges": [
                    {
                        "benefit": {
                            "id": f"benefit-{index}",
                            "name": "Reward",
                            "distributionType": "DIRECT_ENTITLEMENT",
                            "imageAssetURL": "https://example.com/reward.png",
                        }
                    }
                ],
                "startAt": starts_at,
                "endAt": ends_at,
                "preconditionDrops": None,
                "requiredMinutesWatched": 60,
            }
            for index in range(drops)
        ],
    }


def make_campaign(twitch: FakeTwitch, **kwargs) -> DropsCampaign:
    return DropsCampaign(twitch, campaign_data(**kwargs), {})


def test_campaign_image_uses_cdn_display_size() -> None:
    sized = campaign_image_url(
        "https://static-cdn.jtvnw.net/ttv-boxart/515025-285x380.jpg"
    )
    assert sized == "https://static-cdn.jtvnw.net/ttv-boxart/515025-108x144.jpg"

    # No size suffix yet: add the display size instead of downloading the original.
    unsized = campaign_image_url("https://static-cdn.jtvnw.net/ttv-boxart/515025.jpg")
    assert unsized == "https://static-cdn.jtvnw.net/ttv-boxart/515025-108x144.jpg"

    # Non-Twitch URLs keep the previous dimension-stripping behaviour.
    other = campaign_image_url("https://example.com/art-285x380.jpg")
    assert other == "https://example.com/art.jpg"

    assert CAMPAIGN_IMAGE_SIZE == (108, 144)


def test_campaign_uses_sized_box_art() -> None:
    campaign = make_campaign(FakeTwitch())
    assert campaign.image_url.endswith("-108x144.jpg")


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, CampaignStatus.ACTIVE),
        ({"start_offset": 3600, "end_offset": 7200, "status": "UPCOMING"}, CampaignStatus.UPCOMING),
        ({"start_offset": -7200, "end_offset": -3600, "status": "EXPIRED"}, CampaignStatus.EXPIRED),
    ],
)
def test_campaign_status_is_a_single_explicit_value(kwargs, expected) -> None:
    campaign = make_campaign(FakeTwitch(), **kwargs)
    assert campaign.status is expected
    assert campaign.active is (expected is CampaignStatus.ACTIVE)
    assert campaign.upcoming is (expected is CampaignStatus.UPCOMING)
    assert campaign.expired is (expected is CampaignStatus.EXPIRED)


def test_active_campaign_is_not_upcoming_or_expired() -> None:
    campaign = make_campaign(FakeTwitch())
    statuses = {campaign.active, campaign.upcoming, campaign.expired}
    assert statuses == {True, False}


def test_drop_status_available_then_in_progress_then_estimated() -> None:
    campaign = make_campaign(FakeTwitch())
    drop = campaign.get_drop("drop-0")
    assert drop is not None
    assert drop.status is DropStatus.AVAILABLE
    assert drop.is_estimated is False

    drop.real_current_minutes = 10
    assert drop.status is DropStatus.IN_PROGRESS
    assert drop.is_estimated is False

    drop.extra_current_minutes = 1
    assert drop.is_estimated is True
    assert drop.status is DropStatus.IN_PROGRESS
    assert drop.current_minutes == 11


def test_drop_status_saturated_is_not_earnable() -> None:
    campaign = make_campaign(FakeTwitch())
    drop = campaign.get_drop("drop-0")
    assert drop is not None
    drop.extra_current_minutes = MAX_EXTRA_MINUTES

    assert drop.is_saturated is True
    assert drop.status is DropStatus.SATURATED
    assert drop.can_earn() is False


def test_drop_status_claimed_beats_ready_to_claim() -> None:
    campaign = make_campaign(FakeTwitch())
    drop = campaign.get_drop("drop-0")
    assert drop is not None

    drop.claim_id = "user#campaign#drop-0"
    assert drop.can_claim is True
    assert drop.status is DropStatus.READY_TO_CLAIM

    drop.is_claimed = True
    assert drop.status is DropStatus.CLAIMED


def test_drop_status_locked_until_precondition_is_claimed() -> None:
    data = campaign_data(drops=2)
    data["timeBasedDrops"][1]["preconditionDrops"] = [{"id": "drop-0"}]
    campaign = DropsCampaign(FakeTwitch(), data, {})
    first = campaign.get_drop("drop-0")
    second = campaign.get_drop("drop-1")
    assert first is not None and second is not None

    assert second.status is DropStatus.LOCKED
    first.is_claimed = True
    assert second.status is DropStatus.AVAILABLE


def test_missing_precondition_is_treated_as_unmet_instead_of_crashing() -> None:
    campaign = make_campaign(FakeTwitch())
    drop = campaign.get_drop("drop-0")
    assert drop is not None
    drop.precondition_drops = ["does-not-exist"]
    assert drop.preconditions_met is False
    assert drop.status is DropStatus.LOCKED


def test_drop_status_upcoming_and_expired() -> None:
    campaign = make_campaign(FakeTwitch())
    drop = campaign.get_drop("drop-0")
    assert drop is not None

    drop.starts_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert drop.status is DropStatus.UPCOMING

    expired = make_campaign(FakeTwitch(), end_offset=-60)
    expired_drop = expired.get_drop("drop-0")
    assert expired_drop is not None
    assert expired_drop.status is DropStatus.EXPIRED


def test_saturated_drop_requests_an_inventory_reload() -> None:
    twitch = FakeTwitch()
    campaign = make_campaign(twitch)
    drop = campaign.get_drop("drop-0")
    assert drop is not None
    drop.extra_current_minutes = MAX_EXTRA_MINUTES - 1

    class FakeChannel:
        game = campaign.game

    campaign.bump_minutes(FakeChannel())  # type: ignore[arg-type]

    assert drop.is_saturated is True
    assert twitch.changes, "saturation must request a recovery state change"
    assert twitch.changes[-1][0] is State.INVENTORY_FETCH
    assert twitch.prints, "the user must be told why the miner is resyncing"


def test_negative_minutes_delta_clamps_to_zero() -> None:
    campaign = make_campaign(FakeTwitch())
    drop = campaign.get_drop("drop-0")
    assert drop is not None
    drop.real_current_minutes = 5

    drop._update_real_minutes(-10)

    assert drop.real_current_minutes == 0
    assert drop.current_minutes == 0
