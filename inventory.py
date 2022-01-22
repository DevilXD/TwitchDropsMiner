from __future__ import annotations

from datetime import datetime
from functools import cached_property
from typing import Optional, List, Dict, Set, Iterable, TYPE_CHECKING

from channel import Channel
from utils import invalidate_cache, Game
from constants import JsonType, GQL_OPERATIONS

if TYPE_CHECKING:
    from twitch import Twitch


class BaseDrop:
    def __init__(self, campaign: DropsCampaign, data: JsonType, claimed_benefits: Set[str]):
        self._twitch: Twitch = campaign._twitch
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.campaign: DropsCampaign = campaign
        self.rewards: List[str] = [b["benefit"]["name"] for b in data["benefitEdges"]]
        self.starts_at: datetime = datetime.strptime(data["startAt"], "%Y-%m-%dT%H:%M:%SZ")
        self.ends_at: datetime = datetime.strptime(data["endAt"], "%Y-%m-%dT%H:%M:%SZ")
        self.claim_id: Optional[str] = None
        self.is_claimed: bool = False
        if "self" in data:
            self.claim_id = data["self"]["dropInstanceID"]
            self.is_claimed = data["self"]["isClaimed"]
        elif all(b["benefit"]["id"] in claimed_benefits for b in data["benefitEdges"]):
            # NOTE: this may erroneously mark drops from an unprogressed campaign as claimed
            # if the benefits repeat, but shouldn't cause a problem
            # once the campaign is in-progress
            self.is_claimed = True
        self._precondition_drops: List[str] = [d["id"] for d in (data["preconditionDrops"] or [])]

    def __repr__(self) -> str:
        if self.is_claimed:
            additional = ", claimed=True"
        elif self.can_earn:
            additional = ", can_earn=True"
        else:
            additional = ''
        return f"Drop({self.rewards_text()}{additional})"

    @cached_property
    def preconditions(self) -> bool:
        campaign = self.campaign
        return all(campaign.timed_drops[pid].is_claimed for pid in self._precondition_drops)

    @property
    def can_earn(self) -> bool:
        return (
            self.preconditions  # preconditions are met
            and not self.is_claimed  # drop isn't already claimed
            and self.campaign.active  # campaign is active
            and self.starts_at <= datetime.utcnow() < self.ends_at  # it's within the timeframe
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
    def __init__(self, campaign: DropsCampaign, data: JsonType, claimed_benefits: Set[str]):
        super().__init__(campaign, data, claimed_benefits)
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
        elif self.can_earn:
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
        self.campaign._twitch.gui.progress.display(self, countdown=countdown, subone=subone)

    def bump_minutes(self):
        if self.current_minutes < self.required_minutes:
            self.current_minutes += 1
            self._on_minutes_changed()


class DropsCampaign:
    def __init__(self, twitch: Twitch, data: JsonType, claimed_benefits: Set[str]):
        self._twitch: Twitch = twitch
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.game: Game = Game(data["game"])
        self.starts_at: datetime = datetime.strptime(data["startAt"], "%Y-%m-%dT%H:%M:%SZ")
        self.ends_at: datetime = datetime.strptime(data["endAt"], "%Y-%m-%dT%H:%M:%SZ")
        allowed = data["allow"]
        self.allowed_channels: List[Channel] = (
            [
                Channel(twitch, ch["id"], ch["displayName"], priority=True)
                for ch in allowed["channels"]
            ]
            if allowed["channels"] and allowed["isEnabled"] else []
        )
        self.timed_drops: Dict[str, TimedDrop] = {
            drop_data["id"]: TimedDrop(self, drop_data, claimed_benefits)
            for drop_data in data["timeBasedDrops"]
        }

    def __repr__(self) -> str:
        return f"Campaign({self.name}({self.game!s}), {self.claimed_drops}/{self.total_drops})"

    @property
    def drops(self) -> Iterable[TimedDrop]:
        return self.timed_drops.values()

    @property
    def active(self):
        return self.starts_at <= datetime.utcnow() < self.ends_at

    @property
    def upcoming(self) -> bool:
        return datetime.utcnow() < self.starts_at

    @property
    def expired(self) -> bool:
        return self.ends_at <= datetime.utcnow()

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
