from __future__ import annotations

import re
from typing import TYPE_CHECKING
from functools import cached_property
from datetime import datetime, timezone

from channel import Channel
from constants import GQL_OPERATIONS, URLType
from utils import timestamp, invalidate_cache, Game

if TYPE_CHECKING:
    from collections import abc

    from twitch import Twitch
    from gui import GUIManager
    from constants import JsonType


DIMS_PATTERN = re.compile(r'-\d+x\d+(?=\.(?:jpg|png|gif)$)', re.I)


def remove_dimensions(url: URLType) -> URLType:
    return URLType(DIMS_PATTERN.sub('', url))


class BaseDrop:
    def __init__(
        self, campaign: DropsCampaign, data: JsonType, claimed_benefits: dict[str, datetime]
    ):
        self._twitch: Twitch = campaign._twitch
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.campaign: DropsCampaign = campaign
        self.rewards: list[str] = [b["benefit"]["name"] for b in data["benefitEdges"]]
        # we use the first benefit's image specifically here
        self.image_url: URLType = data["benefitEdges"][0]["benefit"]["imageAssetURL"]
        self.starts_at: datetime = timestamp(data["startAt"])
        self.ends_at: datetime = timestamp(data["endAt"])
        self.claim_id: str | None = None
        self.is_claimed: bool = False
        if "self" in data:
            self.claim_id = data["self"]["dropInstanceID"]
            self.is_claimed = data["self"]["isClaimed"]
        elif (
            # If there's no self edge available, we can use claimed_benefits to determine
            # (with pretty good certainty) if this drop has been claimed or not.
            # To do this, we check if the benefitEdges appear in claimed_benefits, and then
            # deref their "lastAwardedAt" timestamps into a list to check against.
            # If the benefits were claimed while the drop was active,
            # the drop has been claimed too.
            (
                dts := [
                    claimed_benefits[bid]
                    for b in data["benefitEdges"]
                    if (bid := b["benefit"]["id"]) in claimed_benefits
                ]
            )
            and all(self.starts_at <= dt < self.ends_at for dt in dts)
        ):
            self.is_claimed = True
        self._precondition_drops: list[str] = [d["id"] for d in (data["preconditionDrops"] or [])]

    def __repr__(self) -> str:
        if self.is_claimed:
            additional = ", claimed=True"
        elif self.can_earn():
            additional = ", can_earn=True"
        else:
            additional = ''
        return f"Drop({self.rewards_text()}{additional})"

    @cached_property
    def preconditions(self) -> bool:
        campaign = self.campaign
        return all(campaign.timed_drops[pid].is_claimed for pid in self._precondition_drops)

    def can_earn(self, channel: Channel | None = None) -> bool:
        return (
            self.preconditions  # preconditions are met
            and not self.is_claimed  # drop isn't already claimed
            and self.campaign.active  # campaign is active
            # drop is within the active timeframe
            and self.starts_at <= datetime.now(timezone.utc) < self.ends_at
            # channel isn't specified, or there's no ACL, or the channel is in the ACL
            and (
                channel is None
                or not (allowed_channels := self.campaign.allowed_channels)
                or channel in allowed_channels
            )
        )

    @property
    def can_claim(self) -> bool:
        return self.claim_id is not None

    def _on_claim(self) -> None:
        invalidate_cache(self, "preconditions")

    def update_claim(self, claim_id: str):
        self.claim_id = claim_id

    def rewards_text(self, delim: str = ", ") -> str:
        return delim.join(self.rewards)

    async def claim(self) -> bool:
        result = await self._claim()
        if result:
            self.is_claimed = True
            # notify the campaign about claiming
            # this will cause it to call our _on_claim, so no need to call it ourselves here
            self.campaign._on_claim()
        return result

    async def _claim(self) -> bool:
        """
        Returns True if the claim succeeded, False otherwise.
        """
        if self.is_claimed:
            return True
        if not self.can_claim:
            return False
        response = await self._twitch.gql_request(
            GQL_OPERATIONS["ClaimDrop"].with_variables(
                {"input": {"dropInstanceID": self.claim_id}}
            )
        )
        data = response["data"]
        if "errors" in data and data["errors"]:
            return False
        elif "claimDropRewards" in data:
            if not data["claimDropRewards"]:
                return False
            elif (
                data["claimDropRewards"]["status"]
                in ["ELIGIBLE_FOR_ALL", "DROP_INSTANCE_ALREADY_CLAIMED"]
            ):
                return True
        return False


class TimedDrop(BaseDrop):
    def __init__(
        self, campaign: DropsCampaign, data: JsonType, claimed_benefits: dict[str, datetime]
    ):
        super().__init__(campaign, data, claimed_benefits)
        self._manager: GUIManager = self._twitch.gui
        self.current_minutes: int = 0
        if "self" in data:
            self.current_minutes = data["self"]["currentMinutesWatched"]
        self.required_minutes: int = data["requiredMinutesWatched"]
        if self.is_claimed:
            # claimed drops report 0 current minutes, so we need to make a correction
            self.current_minutes = self.required_minutes

    def __repr__(self) -> str:
        if self.is_claimed:
            additional = ", claimed=True"
        elif self.can_earn():
            additional = ", can_earn=True"
        else:
            additional = ''
        if 0 < self.current_minutes < self.required_minutes:
            minutes = f", {self.current_minutes}/{self.required_minutes}"
        else:
            minutes = ''
        return f"Drop({self.rewards_text()}{minutes}{additional})"

    @cached_property
    def remaining_minutes(self) -> int:
        return self.required_minutes - self.current_minutes

    @cached_property
    def progress(self) -> float:
        return self.current_minutes / self.required_minutes

    def _on_minutes_changed(self) -> None:
        invalidate_cache(self, "progress", "remaining_minutes")
        self.campaign._on_minutes_changed()

    async def claim(self) -> bool:
        result = await super().claim()
        if result:
            self.current_minutes = self.required_minutes
        return result

    def update_minutes(self, minutes: int):
        self.current_minutes = minutes
        self._on_minutes_changed()

    def display(self, *, countdown: bool = True, subone: bool = False):
        self._manager.display_drop(self, countdown=countdown, subone=subone)

    def bump_minutes(self):
        if self.current_minutes < self.required_minutes:
            self.current_minutes += 1
            self._on_minutes_changed()


class DropsCampaign:
    def __init__(self, twitch: Twitch, data: JsonType, claimed_benefits: dict[str, datetime]):
        self._twitch: Twitch = twitch
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.game: Game = Game(data["game"])
        # campaign's image actually comes from the game object
        # we use regex to get rid of the dimensions part (ex. ".../game_id-285x380.jpg")
        self.image_url: URLType = remove_dimensions(data["game"]["boxArtURL"])
        self.starts_at: datetime = timestamp(data["startAt"])
        self.ends_at: datetime = timestamp(data["endAt"])
        allowed: JsonType = data["allow"]
        self.allowed_channels: list[Channel] = (
            [Channel.from_acl(twitch, channel_data) for channel_data in allowed["channels"]]
            if allowed["channels"] and allowed.get("isEnabled", True) else []
        )
        self.timed_drops: dict[str, TimedDrop] = {
            drop_data["id"]: TimedDrop(self, drop_data, claimed_benefits)
            for drop_data in data["timeBasedDrops"]
        }

    def __repr__(self) -> str:
        return f"Campaign({self.name}({self.game!s}), {self.claimed_drops}/{self.total_drops})"

    @property
    def drops(self) -> abc.Iterable[TimedDrop]:
        return self.timed_drops.values()

    @property
    def active(self):
        return self.starts_at <= datetime.now(timezone.utc) < self.ends_at

    @property
    def upcoming(self) -> bool:
        return datetime.now(timezone.utc) < self.starts_at

    @property
    def expired(self) -> bool:
        return self.ends_at <= datetime.now(timezone.utc)

    @property
    def total_drops(self) -> int:
        return len(self.timed_drops)

    @cached_property
    def claimed_drops(self) -> int:
        return sum(d.is_claimed for d in self.drops)

    @cached_property
    def remaining_drops(self) -> int:
        return sum(not d.is_claimed for d in self.drops)

    @cached_property
    def remaining_minutes(self) -> int:
        return sum(d.remaining_minutes for d in self.timed_drops.values())

    @cached_property
    def progress(self) -> float:
        return sum(d.progress for d in self.drops) / self.total_drops

    def _on_claim(self) -> None:
        invalidate_cache(self, "claimed_drops", "remaining_drops")
        for drop in self.drops:
            drop._on_claim()

    def _on_minutes_changed(self) -> None:
        invalidate_cache(self, "progress", "remaining_minutes")

    def get_drop(self, drop_id: str) -> TimedDrop | None:
        return self.timed_drops.get(drop_id)
