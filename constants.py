from __future__ import annotations

import logging
from copy import copy
from enum import Enum, auto
from datetime import timedelta
from typing import Any, Optional, Dict, Literal, Callable

# Typing
JsonType = Dict[str, Any]
TopicProcess = Callable[[int, JsonType], Any]
# Values
MAX_WEBSOCKETS = 8
WS_TOPICS_LIMIT = 50
# URLs
BASE_URL = "https://twitch.tv"
AUTH_URL = "https://passport.twitch.tv"
WEBSOCKET_URL = "wss://pubsub-edge.twitch.tv/v1"
GQL_URL = "https://gql.twitch.tv/gql"
# Misc for Twitch
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/96.0.4664.45 Safari/537.36"
)
# Paths
LOG_PATH = "log.txt"
COOKIES_PATH = "cookies.jar"
SETTINGS_PATH = "settings.json"
# Intervals and Delays
PING_INTERVAL = timedelta(minutes=3)
PING_TIMEOUT = timedelta(seconds=10)
ONLINE_DELAY = timedelta(seconds=60)
WATCH_INTERVAL = timedelta(seconds=58.8)
# Tags
DROPS_ENABLED_TAG = "c2542d6d-cd10-4532-919b-3d19f30a768b"
FORMATTER = logging.Formatter(
    "{asctime}.{msecs:03.0f}:\t{levelname:>7}:\t{message}",
    style='{',
    datefmt="%Y-%m-%d %H:%M:%S",
)


class State(Enum):
    INVENTORY_FETCH = auto()
    GAMES_UPDATE = auto()
    GAME_SELECT = auto()
    CHANNELS_FETCH = auto()
    CHANNELS_CLEANUP = auto()
    CHANNEL_SWITCH = auto()


class GQLOperation(JsonType):
    def __init__(self, name: str, sha256: str, *, variables: Optional[JsonType] = None):
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


GQL_OPERATIONS: Dict[str, GQLOperation] = {
    "IsStreamLive": GQLOperation(
        "WithIsStreamLiveQuery",
        "04e46329a6786ff3a81c01c50bfa5d725902507a0deb83b0edbf7abe7a3716ea",
    ),
    # returns stream information for a particular channel
    "GetStreamInfo": GQLOperation(
        "VideoPlayerStreamInfoOverlayChannel",
        "a5f2e34d626a9f4f5c0204f910bab2194948a9502089be558bb6e779a9e1b3d2",
    ),
    # can be used to claim channel points
    "ClaimCommunityPoints": GQLOperation(
        "ClaimCommunityPoints",
        "46aaeebe02c99afdf4fc97c7c0cba964124bf6b0af229395f1f6d1feed05b3d0",
    ),
    # can be used to claim a drop
    "ClaimDrop": GQLOperation(
        "DropsPage_ClaimDropRewards",
        "2f884fa187b8fadb2a49db0adc033e636f7b6aaee6e76de1e2bba9a7baf0daf6",
    ),
    # returns current state of points (balance, claim available) for a particular channel
    "ChannelPointsContext": GQLOperation(
        "ChannelPointsContext",
        "9988086babc615a918a1e9a722ff41d98847acac822645209ac7379eecb27152",
    ),
    # returns all in-progress campaigns
    "Inventory": GQLOperation(
        "Inventory",
        "e0765ebaa8e8eeb4043cc6dfeab3eac7f682ef5f724b81367e6e55c7aef2be4c",
    ),
    # returns current state of drops (current drop progress)
    "CurrentDrop": GQLOperation(
        "DropCurrentSessionContext",
        "2e4b3630b91552eb05b76a94b6850eb25fe42263b7cf6d06bee6d156dd247c1c",
    ),
    # returns all available campaigns
    "Campaigns": GQLOperation(
        "ViewerDropsDashboard",
        "e8b98b52bbd7ccd37d0b671ad0d47be5238caa5bea637d2a65776175b4a23a64",
    ),
    # returns extended information about a particular campaign
    "CampaignDetails": GQLOperation(
        "DropCampaignDetails",
        "f6396f5ffdde867a8f6f6da18286e4baf02e5b98d14689a69b5af320a4c7b7b8",
        variables={
            "channelLogin": ...,  # user ID
            "dropID": ...,  # campaign ID
        },
    ),
    # returns drops available for a particular channel
    "ChannelDrops": GQLOperation(
        "DropsHighlightService_AvailableDrops",
        "b19ee96a0e79e3f8281c4108bc4c7b3f232266db6f96fd04a339ab393673a075",
        variables={"channelID": ...},
    ),
    "PersonalSections": GQLOperation(
        "PersonalSections",
        "9fbdfb00156f754c26bde81eb47436dee146655c92682328457037da1a48ed39",
        variables={
            "input": {
                "sectionInputs": ["FOLLOWED_SECTION"],
                "recommendationContext": {"platform": "web"},
            },
            "channelLogin": None,
            "withChannelUser": False,
            "creatorAnniversariesExperimentEnabled": False,
        },
    ),
    # returns live channels for a particular game
    "GameDirectory": GQLOperation(
        "DirectoryPage_Game",
        "d5c5df7ab9ae65c3ea0f225738c08a36a4a76e4c6c31db7f8c4b8dc064227f9e",
        variables={
            "limit": 40,
            "name": "<game_name>",
            "options": {
                "includeRestricted": ["SUB_ONLY_LIVE"],
                "recommendationsContext": {"platform": "web"},
                "sort": "RELEVANCE",
                "tags": [],
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
    def as_str(cls, category: Literal["User", "Channel"], topic_name: str, target_id: int) -> str:
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


WEBSOCKET_TOPICS: Dict[str, Dict[str, str]] = {
    "User": {  # Using user_id
        "Drops": "user-drop-events",
        "StreamState": "stream-change-v1",
        "CommunityPoints": "community-points-user-v1",
        "Presence": "presence",
        "Notifications": "onsite-notifications",
    },
    "Channel": {  # Using channel_id
        "Drops": "channel-drop-events",
        "StreamState": "stream-change-by-channel",
        "CommunityPoints": "community-points-channel-v1",
        "VideoPlayback": "video-playback-by-id",
        "StreamUpdate": "broadcast-settings-update",
    },
}
