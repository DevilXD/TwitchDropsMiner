from __future__ import annotations

import sys
import logging
from copy import copy
from pathlib import Path
from enum import Enum, auto
from datetime import timedelta
from typing import Any, Dict, Literal, NewType, TYPE_CHECKING

from version import __version__

if TYPE_CHECKING:
    from collections import abc  # noqa
    from typing_extensions import TypeAlias


# Base Paths
SELF_PATH = Path(sys.argv[0])
WORKING_DIR = SELF_PATH.absolute().parent
# Other Paths
LOG_PATH = Path(WORKING_DIR, "log.txt")
CACHE_PATH = Path(WORKING_DIR, "cache")
CACHE_DB = Path(CACHE_PATH, "mapping.json")
COOKIES_PATH = Path(WORKING_DIR, "cookies.jar")
SETTINGS_PATH = Path(WORKING_DIR, "settings.json")
# Typing
JsonType = Dict[str, Any]
URLType = NewType("URLType", str)
TopicProcess: TypeAlias = "abc.Callable[[int, JsonType], Any]"
# Values
MAX_WEBSOCKETS = 8
WS_TOPICS_LIMIT = 50
# Misc
BASE_URL = "https://twitch.tv"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/99.0.4844.51 Safari/537.36"
)
# Intervals and Delays
PING_INTERVAL = timedelta(minutes=3)
PING_TIMEOUT = timedelta(seconds=10)
ONLINE_DELAY = timedelta(seconds=120)
WATCH_INTERVAL = timedelta(seconds=59)
# Strings
DROPS_ENABLED_TAG = "c2542d6d-cd10-4532-919b-3d19f30a768b"
WINDOW_TITLE = f"Twitch Drops Miner v{__version__} (by DevilXD)"
# Logging
FORMATTER = logging.Formatter(
    "{asctime}.{msecs:03.0f}:\t{levelname:>7}:\t{message}",
    style='{',
    datefmt="%Y-%m-%d %H:%M:%S",
)


class State(Enum):
    IDLE = auto()
    INVENTORY_FETCH = auto()
    GAMES_UPDATE = auto()
    CHANNELS_FETCH = auto()
    CHANNELS_CLEANUP = auto()
    CHANNEL_SWITCH = auto()
    EXIT = auto()


class GQLOperation(JsonType):
    def __init__(self, name: str, sha256: str, *, variables: JsonType | None = None):
        super().__init__(
            operationName=name,
            extensions={
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": sha256,
                }
            }
        )
        if variables is not None:
            self.__setitem__("variables", variables)

    def with_variables(self, variables: JsonType):
        modified = copy(self)
        if "variables" in self:
            existing_variables: JsonType = modified["variables"]
            existing_variables.update(variables)
        else:
            modified["variables"] = variables
        return modified


GQL_OPERATIONS: dict[str, GQLOperation] = {
    # returns stream information for a particular channel
    "GetStreamInfo": GQLOperation(
        "VideoPlayerStreamInfoOverlayChannel",
        "a5f2e34d626a9f4f5c0204f910bab2194948a9502089be558bb6e779a9e1b3d2",
        variables={
            "channel": ...,  # channel login
        },
    ),
    # can be used to claim channel points
    "ClaimCommunityPoints": GQLOperation(
        "ClaimCommunityPoints",
        "46aaeebe02c99afdf4fc97c7c0cba964124bf6b0af229395f1f6d1feed05b3d0",
        variables={
            "input": {
                "claimID": ...,  # points claim_id
                "channelID": ...,  # channel ID as a str
            },
        },
    ),
    # can be used to claim a drop
    "ClaimDrop": GQLOperation(
        "DropsPage_ClaimDropRewards",
        "2f884fa187b8fadb2a49db0adc033e636f7b6aaee6e76de1e2bba9a7baf0daf6",
        variables={
            "input": {
                "dropInstanceID": ...,  # drop claim_id
            },
        },
    ),
    # returns current state of points (balance, claim available) for a particular channel
    "ChannelPointsContext": GQLOperation(
        "ChannelPointsContext",
        "9988086babc615a918a1e9a722ff41d98847acac822645209ac7379eecb27152",
        variables={
            "channelLogin": ...,  # channel login
        },
    ),
    # returns all in-progress campaigns
    "Inventory": GQLOperation(
        "Inventory",
        "27f074f54ff74e0b05c8244ef2667180c2f911255e589ccd693a1a52ccca7367",
        # no variables needed
    ),
    # returns current state of drops (current drop progress)
    "CurrentDrop": GQLOperation(
        "DropCurrentSessionContext",
        "2e4b3630b91552eb05b76a94b6850eb25fe42263b7cf6d06bee6d156dd247c1c",
        # no variables needed
    ),
    # returns all available campaigns
    "Campaigns": GQLOperation(
        "ViewerDropsDashboard",
        "e8b98b52bbd7ccd37d0b671ad0d47be5238caa5bea637d2a65776175b4a23a64",
        # no variables needed
    ),
    # returns extended information about a particular campaign
    "CampaignDetails": GQLOperation(
        "DropCampaignDetails",
        "f6396f5ffdde867a8f6f6da18286e4baf02e5b98d14689a69b5af320a4c7b7b8",
        variables={
            "channelLogin": ...,  # user login
            "dropID": ...,  # campaign ID
        },
    ),
    # returns drops available for a particular channel (unused)
    "ChannelDrops": GQLOperation(
        "DropsHighlightService_AvailableDrops",
        "b19ee96a0e79e3f8281c4108bc4c7b3f232266db6f96fd04a339ab393673a075",
        variables={
            "channelID": ...,  # channel ID as a str
        },
    ),
    # returns live channels for a particular game
    "GameDirectory": GQLOperation(
        "DirectoryPage_Game",
        "d5c5df7ab9ae65c3ea0f225738c08a36a4a76e4c6c31db7f8c4b8dc064227f9e",
        variables={
            "limit": ...,  # limit of channels returned
            "name": ...,  # game name
            "options": {
                "includeRestricted": ["SUB_ONLY_LIVE"],
                "recommendationsContext": {"platform": "web"},
                "sort": "RELEVANCE",
                "tags": [],  # list of tag IDs
                "requestID": "JIRA-VXP-2397",
            },
            "sortTypeIsRecency": False,
        },
    ),
}


class WebsocketTopic:
    def __init__(
        self,
        category: Literal["User", "Channel"],
        topic_name: str,
        target_id: int,
        process: TopicProcess,
    ):
        self._id: str = f"{WEBSOCKET_TOPICS[category][topic_name]}.{target_id}"
        assert isinstance(target_id, int)
        self._target_id = target_id
        self._process: TopicProcess = process

    @classmethod
    def as_str(
        cls, category: Literal["User", "Channel"], topic_name: str, target_id: int
    ) -> str:
        return f"{WEBSOCKET_TOPICS[category][topic_name]}.{target_id}"

    def __call__(self, message: JsonType):
        return self._process(self._target_id, message)

    def __str__(self) -> str:
        return self._id

    def __repr__(self) -> str:
        return f"Topic({self._id})"

    def __eq__(self, other):
        if isinstance(other, WebsocketTopic):
            return self._id == other._id
        elif isinstance(other, str):
            return self._id == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, self._id))


WEBSOCKET_TOPICS: dict[str, dict[str, str]] = {
    "User": {  # Using user_id
        "Drops": "user-drop-events",
        "CommunityPoints": "community-points-user-v1",
        "Presence": "presence",  # unused
        "Notifications": "onsite-notifications",  # unused
    },
    "Channel": {  # Using channel_id
        "Drops": "channel-drop-events",  # unused
        "CommunityPoints": "community-points-channel-v1",  # unused
        "StreamState": "video-playback-by-id",
        # currently unused, can be used to receive updates regarding stream's title and tag changes
        "StreamUpdate": "broadcast-settings-update",
    },
}
