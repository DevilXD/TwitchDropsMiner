from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, TYPE_CHECKING

from constants import JsonType, GQL_OPERATIONS

if TYPE_CHECKING:
    from twitch import Twitch


class Game:
    def __init__(self, data: JsonType):
        self.id: int = int(data["id"])
        self.name: str = data["name"]

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object):
        if isinstance(other, self.__class__):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, self.id))


class BaseDrop:
    def __init__(self, campaign: DropsCampaign, data: JsonType):
        self._twitch: Twitch = campaign._twitch
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.campaign: DropsCampaign = campaign
        self.rewards: List[str] = [b["benefit"]["name"] for b in data["benefitEdges"]]
        self.starts_at: datetime = datetime.strptime(data["startAt"], "%Y-%m-%dT%H:%M:%SZ")
        self.ends_at: datetime = datetime.strptime(data["endAt"], "%Y-%m-%dT%H:%M:%SZ")
        # If claim_id is not None, we can use it to claim the drop
        self.claim_id: Optional[str] = data["self"]["dropInstanceID"]
        self.is_claimed: bool = data["self"]["isClaimed"]
        self._preconditions: bool = data["self"]["hasPreconditionsMet"]

    @property
    def can_earn(self) -> bool:
        return (
            self._preconditions  # preconditions are met
            and self.campaign.active  # campaign is active
            and not self.is_claimed  # drop isn't already claimed
        )

    @property
    def can_claim(self) -> bool:
        return self.claim_id is not None and not self.is_claimed

    def rewards_text(self, delim: str = ", ") -> str:
        return delim.join(self.rewards)

    async def claim(self) -> bool:
        """
        Returns True if the claim succeeded, False otherwise.
        """
        if not self.can_claim:
            return False
        if self.is_claimed:
            return True
        op = GQL_OPERATIONS["ClaimDrop"].with_variables(
            {"input": {"dropInstanceID": self.claim_id}}
        )
        response = await self._twitch.gql_request(op)
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
                self.is_claimed = True
                return True
        return False


class TimedDrop(BaseDrop):
    def __init__(self, campaign: DropsCampaign, data: JsonType):
        super().__init__(campaign, data)
        self.current_minutes: int = data["self"]["currentMinutesWatched"]
        self.required_minutes: int = data["requiredMinutesWatched"]
        if self.is_claimed:
            # claimed drops report 0 current minutes, so we need to make a correction
            self.current_minutes = self.required_minutes

    @property
    def remaining_minutes(self) -> int:
        return self.required_minutes - self.current_minutes

    @property
    def progress(self) -> float:
        return self.current_minutes / self.required_minutes

    def update(self, message: JsonType):
        # {"type": "drop-progress", data: {"current_progress_min": 3, "required_progress_min": 10}}
        # {"type": "drop-claim", data: {"drop_instance_id": ...}}
        msg_type = message["type"]
        if msg_type == "drop-progress":
            self.current_minutes = message["data"]["current_progress_min"]
            self.required_minutes = message["data"]["required_progress_min"]
        elif msg_type == "drop-claim":
            self.claim_id = message["data"]["drop_instance_id"]


class DropsCampaign:
    def __init__(self, twitch: Twitch, data: JsonType):
        self._twitch: Twitch = twitch
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.game: Game = Game(data["game"])
        self.starts_at: datetime = datetime.strptime(data["startAt"], "%Y-%m-%dT%H:%M:%SZ")
        self.ends_at: datetime = datetime.strptime(data["endAt"], "%Y-%m-%dT%H:%M:%SZ")
        self.status: str = data["status"]
        self.timed_drops: Dict[str, TimedDrop] = {
            d["id"]: TimedDrop(self, d) for d in data["timeBasedDrops"]
        }

    @property
    def active(self):
        return self.status == "ACTIVE"

    @property
    def total_drops(self) -> int:
        return len(self.timed_drops)

    @property
    def claimed_drops(self) -> int:
        return sum(d.is_claimed for d in self.timed_drops.values())

    @property
    def remaining_drops(self) -> int:
        return sum(not d.is_claimed for d in self.timed_drops.values())

    @property
    def remaining_minutes(self) -> int:
        return sum(d.remaining_minutes for d in self.timed_drops.values())

    @property
    def progress(self) -> float:
        return sum(d.progress for d in self.timed_drops.values()) / self.total_drops

    def get_drop(self, drop_id: str) -> Optional[TimedDrop]:
        return self.timed_drops.get(drop_id)
