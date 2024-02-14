from __future__ import annotations

import os
import sys
import random
import logging
from pathlib import Path
from copy import deepcopy
from enum import Enum, auto
from datetime import timedelta
from typing import Any, Dict, Literal, NewType, TYPE_CHECKING

from yarl import URL

from version import __version__

if TYPE_CHECKING:
    from collections import abc  # noqa
    from typing_extensions import TypeAlias


# True if we're running from a built EXE (or a Linux AppImage), False inside a dev build
IS_APPIMAGE = "APPIMAGE" in os.environ and os.path.exists(os.environ["APPIMAGE"])
IS_PACKAGED = hasattr(sys, "_MEIPASS") or IS_APPIMAGE
# logging special levels
CALL = logging.INFO - 1
logging.addLevelName(CALL, "CALL")
# site-packages venv path changes depending on the system platform
if sys.platform == "win32":
    SYS_SITE_PACKAGES = "Lib/site-packages"
else:
    # On Linux, the site-packages path includes a versioned 'pythonX.Y' folder part
    # The Lib folder is also spelled in lowercase: 'lib'
    version_info = sys.version_info
    SYS_SITE_PACKAGES = f"lib/python{version_info.major}.{version_info.minor}/site-packages"


def _resource_path(relative_path: Path | str) -> Path:
    """
    Get an absolute path to a bundled resource.

    Works for dev and for PyInstaller.
    """
    if IS_APPIMAGE:
        base_path = Path(sys.argv[0]).absolute().parent
    elif IS_PACKAGED:
        # PyInstaller's folder where the one-file app is unpacked
        meipass: str = getattr(sys, "_MEIPASS")
        base_path = Path(meipass)
    else:
        base_path = WORKING_DIR
    return base_path.joinpath(relative_path)


def _merge_vars(base_vars: JsonType, vars: JsonType) -> None:
    # NOTE: This modifies base in place
    for k, v in vars.items():
        if k not in base_vars:
            base_vars[k] = v
        elif isinstance(v, dict):
            if isinstance(base_vars[k], dict):
                _merge_vars(base_vars[k], v)
            elif base_vars[k] is Ellipsis:
                # unspecified base, use the passed in var
                base_vars[k] = v
            else:
                raise RuntimeError(f"Var is a dict, base is not: '{k}'")
        elif isinstance(base_vars[k], dict):
            raise RuntimeError(f"Base is a dict, var is not: '{k}'")
        else:
            # simple overwrite
            base_vars[k] = v
    # ensure none of the vars are ellipsis (unset value)
    for k, v in base_vars.items():
        if v is Ellipsis:
            raise RuntimeError(f"Unspecified variable: '{k}'")


# Base Paths
if IS_APPIMAGE:
    SELF_PATH = Path(os.environ["APPIMAGE"]).absolute()
else:
    # NOTE: pyinstaller will set sys.argv[0] to its own executable when building,
    # detect this to use __file__ and main.py redirection instead
    SELF_PATH = Path(sys.argv[0]).absolute()
    if SELF_PATH.stem == "pyinstaller":
        SELF_PATH = Path(__file__).with_name("main.py").absolute()
WORKING_DIR = SELF_PATH.parent
# Development paths
VENV_PATH = Path(WORKING_DIR, "env")
SITE_PACKAGES_PATH = Path(VENV_PATH, SYS_SITE_PACKAGES)
# Translations path
# NOTE: These don't have to be available to the end-user, so the path points to the internal dir
LANG_PATH = _resource_path("lang")
# Other Paths
LOG_PATH = Path(WORKING_DIR, "log.txt")
CACHE_PATH = Path(WORKING_DIR, "cache")
LOCK_PATH = Path(WORKING_DIR, "lock.file")
CACHE_DB = Path(CACHE_PATH, "mapping.json")
COOKIES_PATH = Path(WORKING_DIR, "cookies.jar")
SETTINGS_PATH = Path(WORKING_DIR, "settings.json")
# Typing
JsonType = Dict[str, Any]
URLType = NewType("URLType", str)
TopicProcess: TypeAlias = "abc.Callable[[int, JsonType], Any]"
# Values
BASE_TOPICS = 3
MAX_WEBSOCKETS = 8
WS_TOPICS_LIMIT = 50
TOPICS_PER_CHANNEL = 2
MAX_TOPICS = (MAX_WEBSOCKETS * WS_TOPICS_LIMIT) - BASE_TOPICS
MAX_CHANNELS = MAX_TOPICS // TOPICS_PER_CHANNEL
# Misc
DEFAULT_LANG = "English"
# Intervals and Delays
PING_INTERVAL = timedelta(minutes=3)
PING_TIMEOUT = timedelta(seconds=10)
ONLINE_DELAY = timedelta(seconds=120)
WATCH_INTERVAL = timedelta(seconds=59)
# Strings
WINDOW_TITLE = f"Twitch Drops Miner v{__version__} (by DevilXD)"
# Logging
FILE_FORMATTER = logging.Formatter(
    "{asctime}.{msecs:03.0f}:\t{levelname:>7}:\t{message}",
    style='{',
    datefmt="%Y-%m-%d %H:%M:%S",
)
OUTPUT_FORMATTER = logging.Formatter("{levelname}: {message}", style='{', datefmt="%H:%M:%S")


class ClientInfo:
    def __init__(self, client_url: URL, client_id: str, user_agents: str | list[str]) -> None:
        self.CLIENT_URL: URL = client_url
        self.CLIENT_ID: str = client_id
        self.USER_AGENT: str
        if isinstance(user_agents, list):
            self.USER_AGENT = random.choice(user_agents)
        else:
            self.USER_AGENT = user_agents

    def __iter__(self):
        return iter((self.CLIENT_URL, self.CLIENT_ID, self.USER_AGENT))


class ClientType:
    WEB = ClientInfo(
        URL("https://www.twitch.tv"),
        "kimne78kx3ncx6brgo4mv6wki5h1ko",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ),
    )
    MOBILE_WEB = ClientInfo(
        URL("https://m.twitch.tv"),
        "r8s4dac0uhzifbpu9sjdiwzctle17ff",
        [
            (
                "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.6045.66 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 13; SM-A205U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.6045.66 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 13; SM-A102U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.6045.66 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 13; SM-G960U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.6045.66 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 13; SM-N960U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.6045.66 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 13; LM-Q720) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.6045.66 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 13; LM-X420) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.6045.66 Mobile Safari/537.36"
            ),
        ]
    )
    ANDROID_APP = ClientInfo(
        URL("https://www.twitch.tv"),
        "kd1unb4b3q4t58fwlpcbzcbnm76a8fp",
        (
            "Dalvik/2.1.0 (Linux; U; Android 7.1.2; SM-G977N Build/LMY48Z) "
            "tv.twitch.android.app/16.8.1/1608010"
        ),
    )
    SMARTBOX = ClientInfo(
        URL("https://android.tv.twitch.tv"),
        "ue6666qo983tsx6so1t0vnawi233wa",
        (
            "Mozilla/5.0 (Linux; Android 7.1; Smart Box C1) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ),
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

    def with_variables(self, variables: JsonType) -> GQLOperation:
        modified = deepcopy(self)
        if "variables" in self:
            existing_variables: JsonType = modified["variables"]
            _merge_vars(existing_variables, variables)
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
        "a455deea71bdc9015b78eb49f4acfbce8baa7ccbedd28e549bb025bd0f751930",
        variables={
            "input": {
                "dropInstanceID": ...,  # drop claim_id
            },
        },
    ),
    # returns current state of points (balance, claim available) for a particular channel
    "ChannelPointsContext": GQLOperation(
        "ChannelPointsContext",
        "1530a003a7d374b0380b79db0be0534f30ff46e61cffa2bc0e2468a909fbc024",
        variables={
            "channelLogin": ...,  # channel login
        },
    ),
    # returns all in-progress campaigns
    "Inventory": GQLOperation(
        "Inventory",
        "37fea486d6179047c41d0f549088a4c3a7dd60c05c70956a1490262f532dccd9",
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
        "8d5d9b5e3f088f9d1ff39eb2caab11f7a4cf7a3353da9ce82b5778226ff37268",
        # no variables needed
    ),
    # returns extended information about a particular campaign
    "CampaignDetails": GQLOperation(
        "DropCampaignDetails",
        "e5916665a37150808f8ad053ed6394b225d5504d175c7c0b01b9a89634c57136",
        variables={
            "channelLogin": ...,  # user login
            "dropID": ...,  # campaign ID
        },
    ),
    # returns drops available for a particular channel (unused)
    "AvailableDrops": GQLOperation(
        "DropsHighlightService_AvailableDrops",
        "9a62a09bce5b53e26e64a671e530bc599cb6aab1e5ba3cbd5d85966d3940716f",
        variables={
            "channelID": ...,  # channel ID as a str
        },
    ),
    # returns live channels for a particular game
    "GameDirectory": GQLOperation(
        "DirectoryPage_Game",
        "3c9a94ee095c735e43ed3ad6ce6d4cbd03c4c6f754b31de54993e0d48fd54e30",
        variables={
            "limit": ...,  # limit of channels returned
            "slug": ...,  # game slug
            "imageWidth": 50,
            "options": {
                "broadcasterLanguages": [],
                "freeformTags": None,
                "includeRestricted": ["SUB_ONLY_LIVE"],
                "recommendationsContext": {"platform": "web"},
                "sort": "RELEVANCE",
                "tags": [],
                "requestID": "JIRA-VXP-2397",
            },
            "sortTypeIsRecency": False,
        },
    ),
    "NotificationsView": GQLOperation(  # unused, triggers notifications "update-summary"
        "OnsiteNotifications_View",
        "f6bdb1298f376539487f28b7f8a6b5d7434ec04ba4d7dc5c232b258410ae04d6",
        variables={
            "input": {},
        },
    ),
    "NotificationsList": GQLOperation(  # unused
        "OnsiteNotifications_ListNotifications",
        "e709b905ddb963d7cf4a8f6760148926ecbd0eee0f2edc48d1cf17f3e87f6490",
        variables={
            "cursor": "",
            "displayType": "VIEWER",
            "language": "en",
            "limit": 10,
            "shouldLoadLastBroadcast": False,
        },
    ),
    "NotificationsDelete": GQLOperation(
        "OnsiteNotifications_DeleteNotification",
        "13d463c831f28ffe17dccf55b3148ed8b3edbbd0ebadd56352f1ff0160616816",
        variables={
            "input": {
                "id": "",  # ID of the notification to delete
            }
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
        assert isinstance(target_id, int)
        self._id: str = self.as_str(category, topic_name, target_id)
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

    def __eq__(self, other) -> bool:
        if isinstance(other, WebsocketTopic):
            return self._id == other._id
        elif isinstance(other, str):
            return self._id == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, self._id))


WEBSOCKET_TOPICS: dict[str, dict[str, str]] = {
    "User": {  # Using user_id
        "Presence": "presence",  # unused
        "Drops": "user-drop-events",
        "Notifications": "onsite-notifications",
        "CommunityPoints": "community-points-user-v1",
    },
    "Channel": {  # Using channel_id
        "Drops": "channel-drop-events",  # unused
        "StreamState": "video-playback-by-id",
        "StreamUpdate": "broadcast-settings-update",
        "CommunityPoints": "community-points-channel-v1",  # unused
    },
}
