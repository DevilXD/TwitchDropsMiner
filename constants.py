from __future__ import annotations

import sys
import logging
from pathlib import Path
from copy import deepcopy
from enum import Enum, auto
from datetime import timedelta
from typing import Any, Dict, Literal, NamedTuple, NewType, TYPE_CHECKING

from yarl import URL

from version import __version__

if TYPE_CHECKING:
    from collections import abc  # noqa
    from typing_extensions import TypeAlias


# True if we're running from a built EXE, False inside a dev build
IS_PACKAGED = hasattr(sys, "_MEIPASS")
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
    if IS_PACKAGED:
        # PyInstaller's folder where the one-file app is unpacked
        meipass: str = getattr(sys, "_MEIPASS")
        base_path = Path(meipass)
    else:
        base_path = WORKING_DIR
    return base_path.joinpath(relative_path)


# Base Paths
# NOTE: pyinstaller will set this to its own executable when building,
# detect this to use __file__ and main.py redirection instead
SELF_PATH = Path(sys.argv[0]).absolute()
if SELF_PATH.stem == "pyinstaller":
    SELF_PATH = Path(__file__).with_name("main.py").absolute()
WORKING_DIR = SELF_PATH.absolute().parent
# Development paths
VENV_PATH = Path(WORKING_DIR, "env")
SITE_PACKAGES_PATH = Path(VENV_PATH, SYS_SITE_PACKAGES)
# Translations path
# NOTE: These don't have to be available to the end-user, so the path points to the internal dir
LANG_PATH = _resource_path("lang")
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
BASE_TOPICS = 2
MAX_WEBSOCKETS = 8
WS_TOPICS_LIMIT = 50
TOPICS_PER_CHANNEL = 2
MAX_TOPICS = (MAX_WEBSOCKETS * WS_TOPICS_LIMIT) - BASE_TOPICS
MAX_CHANNELS = MAX_TOPICS // TOPICS_PER_CHANNEL
# Misc
DEFAULT_LANG = "English"
BASE_URL = URL("https://twitch.tv")
# Intervals and Delays
PING_INTERVAL = timedelta(minutes=3)
PING_TIMEOUT = timedelta(seconds=10)
ONLINE_DELAY = timedelta(seconds=120)
WATCH_INTERVAL = timedelta(seconds=59)
# Strings
DROPS_ENABLED_TAG = "c2542d6d-cd10-4532-919b-3d19f30a768b"
WINDOW_TITLE = f"Twitch Drops Miner v{__version__} (by DevilXD)"
# Logging
FILE_FORMATTER = logging.Formatter(
    "{asctime}.{msecs:03.0f}:\t{levelname:>7}:\t{message}",
    style='{',
    datefmt="%Y-%m-%d %H:%M:%S",
)
OUTPUT_FORMATTER = logging.Formatter("{levelname}: {message}", style='{', datefmt="%H:%M:%S")


class ClientInfo(NamedTuple):
    CLIENT_ID: str
    USER_AGENT: str


class ClientType:
    WEB = ClientInfo(
        "kimne78kx3ncx6brgo4mv6wki5h1ko",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
        ),
    )
    ANDROID = ClientInfo(
        "kd1unb4b3q4t58fwlpcbzcbnm76a8fp",
        (
            "Dalvik/2.1.0 (Linux; U; Android 7.1.2; SM-G977N Build/LMY48Z) "
            "tv.twitch.android.app/14.3.2/1403020"
        ),
    )
    SMARTBOX = ClientInfo(
        "ue6666qo983tsx6so1t0vnawi233wa",
        (
            "Mozilla/5.0 (Linux; Android 7.1; Smart Box C1) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
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
        "f6396f5ffdde867a8f6f6da18286e4baf02e5b98d14689a69b5af320a4c7b7b8",
        variables={
            "channelLogin": ...,  # user login
            "dropID": ...,  # campaign ID
        },
    ),
    # returns drops available for a particular channel (unused)
    "ChannelDrops": GQLOperation(
        "DropsHighlightService_AvailableDrops",
        "9a62a09bce5b53e26e64a671e530bc599cb6aab1e5ba3cbd5d85966d3940716f",
        variables={
            "channelID": ...,  # channel ID as a str
        },
    ),
    # returns live channels for a particular game
    "GameDirectory": GQLOperation(
        "DirectoryPage_Game",
        "df4bb6cc45055237bfaf3ead608bbafb79815c7100b6ee126719fac3762ddf8b",
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
        "Drops": "user-drop-events",
        "CommunityPoints": "community-points-user-v1",
        "Presence": "presence",  # unused
        "Notifications": "onsite-notifications",  # unused
    },
    "Channel": {  # Using channel_id
        "Drops": "channel-drop-events",  # unused
        "CommunityPoints": "community-points-channel-v1",  # unused
        "StreamState": "video-playback-by-id",
        "StreamUpdate": "broadcast-settings-update",
    },
}
