from __future__ import annotations

from copy import copy
from datetime import timedelta
from typing import Any, Optional, Union, Dict, Callable


BASE_URL = "https://twitch.tv"
AUTH_URL = "https://passport.twitch.tv"
WEBSOCKET_URL = "wss://pubsub-edge.twitch.tv/v1"
GQL_URL = "https://gql.twitch.tv/gql"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/96.0.4664.45 Safari/537.36"
)
SETTINGS_PATH = "settings.json"
COOKIES_PATH = "cookies.pickle"
PING_INTERVAL = timedelta(minutes=3)
ONLINE_DELAY = timedelta(seconds=30)
# tags
DROPS_ENABLED_TAG = "c2542d6d-cd10-4532-919b-3d19f30a768b"


class GQLOperation(Dict[str, Any]):
    def __init__(self, name: str, sha256: str, *, variables: Optional[Dict[str, Any]] = None):
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

    def with_variables(self, variables: Dict[str, Any]):
        modified = copy(self)
        if "variables" in self:
            existing_variables: Dict[str, Any] = modified["variables"]
            existing_variables.update(variables)
        else:
            modified["variables"] = variables
        return modified


GQL_OPERATIONS: Dict[str, GQLOperation] = {
    "IsStreamLive": GQLOperation(
        "WithIsStreamLiveQuery",
        "04e46329a6786ff3a81c01c50bfa5d725902507a0deb83b0edbf7abe7a3716ea",
    ),
    "GetStreamInfo": GQLOperation(  # used
        "VideoPlayerStreamInfoOverlayChannel",
        "a5f2e34d626a9f4f5c0204f910bab2194948a9502089be558bb6e779a9e1b3d2",
    ),
    "ClaimCommunityPoints": GQLOperation(  # used
        "ClaimCommunityPoints",
        "46aaeebe02c99afdf4fc97c7c0cba964124bf6b0af229395f1f6d1feed05b3d0",
    ),
    "ClaimDrop": GQLOperation(  # used
        "DropsPage_ClaimDropRewards",
        "2f884fa187b8fadb2a49db0adc033e636f7b6aaee6e76de1e2bba9a7baf0daf6",
    ),
    "ChannelPointsContext": GQLOperation(  # used
        "ChannelPointsContext",
        "9988086babc615a918a1e9a722ff41d98847acac822645209ac7379eecb27152",
    ),
    "Inventory": GQLOperation(  # used
        "Inventory",
        "e0765ebaa8e8eeb4043cc6dfeab3eac7f682ef5f724b81367e6e55c7aef2be4c",
    ),
    "ViewerDropsDashboard": GQLOperation(
        "ViewerDropsDashboard",
        "c4d61d7b71d03b324914d3cf8ca0bc23fe25dacf54120cc954321b9704a3f4e2",
    ),
    "DropCampaignDetails": GQLOperation(
        "DropCampaignDetails",
        "14b5e8a50777165cfc3971e1d93b4758613fe1c817d5542c398dce70b7a45c05",
    ),
    "AvailableDrops": GQLOperation(
        "DropsHighlightService_AvailableDrops",
        "b19ee96a0e79e3f8281c4108bc4c7b3f232266db6f96fd04a339ab393673a075",
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
    "GameDirectory": GQLOperation(
        "DirectoryPage_Game",
        "d5c5df7ab9ae65c3ea0f225738c08a36a4a76e4c6c31db7f8c4b8dc064227f9e",
        variables={
            "limit": 40,
            "name": "paladins",
            "options": {
                "includeRestricted": ["SUB_ONLY_LIVE"],
                "recommendationsContext": {"platform": "web"},
                "sort": "RELEVANCE",
                "tags": [],
                "requestID": "JIRA-VXP-2397",
            },
            "sortTypeIsRecency": False
        },
    ),
}


def get_topic(
    topic_name: str, target_id: Union[str, int], process: Callable[[Dict[str, Any]], Any]
) -> WebsocketTopic:
    return WebsocketTopic(f"{WEBSOCKET_TOPICS[topic_name]}.{target_id}", process)


class WebsocketTopic:
    def __init__(self, topic_id: str, process: Callable[[Dict[str, Any]], Any]):
        self.id: str = topic_id
        self.process: Callable[[Dict[str, Any]], Any] = process

    def __str__(self) -> str:
        return self.id

    def __eq__(self, other):
        if isinstance(other, str):
            return self.id == other
        elif isinstance(other, WebsocketTopic):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, self.id))


WEBSOCKET_TOPICS: Dict[str, str] = {
    # Using user_id
    "UserDrops": "user-drop-events",
    "UserStreamState": "stream-change-v1",
    "UserCommunityPoints": "community-points-user-v1",
    "Presence": "presence",
    "Notifications": "onsite-notifications",
    # Using channel_id
    "ChannelDrops": "channel-drop-events",
    "ChannelStreamState": "stream-change-by-channel",
    "ChannelCommunityPoints": "community-points-channel-v1",
    "VideoPlayback": "video-playback-by-id",
    "StreamUpdate": "broadcast-settings-update",
}
