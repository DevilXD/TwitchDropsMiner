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
CALL: int = logging.INFO - 1
logging.addLevelName(CALL, "CALL")
# site-packages venv path changes depending on the system platform
if sys.platform == "win32":
    SYS_SITE_PACKAGES = "Lib/site-packages"
else:
    # On Linux, the site-packages path includes a versioned 'pythonX.Y' folder part
    # The Lib folder is also spelled in lowercase: 'lib'
    version_info = sys.version_info
    SYS_SITE_PACKAGES = f"lib/python{version_info.major}.{version_info.minor}/site-packages"
# scripts venv path changes depending on the system platform
if sys.platform == "win32":
    SYS_SCRIPTS = "Scripts"
else:
    SYS_SCRIPTS = "bin"


def _resource_path(relative_path: Path | str) -> Path:
    """
    Get an absolute path to a bundled resource.

    Works for dev and for PyInstaller.
    """
    if IS_APPIMAGE:
        base_path = Path(sys.argv[0]).resolve().parent
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
    SELF_PATH = Path(os.environ["APPIMAGE"]).resolve()
else:
    # NOTE: pyinstaller will set sys.argv[0] to its own executable when building
    # NOTE: sys.argv[0] will point to gui.py when running the gui.py directly for GUI debug
    # detect these and use __file__ and main.py redirection instead
    SELF_PATH = Path(sys.argv[0]).resolve()
    if SELF_PATH.stem == "pyinstaller" or SELF_PATH.name == "gui.py":
        SELF_PATH = Path(__file__).with_name("main.py").resolve()
WORKING_DIR = SELF_PATH.parent
# Development paths
VENV_PATH = Path(WORKING_DIR, "env")
SITE_PACKAGES_PATH = Path(VENV_PATH, SYS_SITE_PACKAGES)
SCRIPTS_PATH = Path(VENV_PATH, SYS_SCRIPTS)
# Translations path
# NOTE: These don't have to be available to the end-user, so the path points to the internal dir
LANG_PATH = _resource_path("lang")
# Other Paths
LOG_PATH = Path(WORKING_DIR, "log.txt")
DUMP_PATH = Path(WORKING_DIR, "dump.dat")
LOCK_PATH = Path(WORKING_DIR, "lock.file")
CACHE_PATH = Path(WORKING_DIR, "cache")
CACHE_DB = Path(CACHE_PATH, "mapping.json")
COOKIES_PATH = Path(WORKING_DIR, "cookies.jar")
SETTINGS_PATH = Path(WORKING_DIR, "settings.json")
# Typing
JsonType = Dict[str, Any]
URLType = NewType("URLType", str)
TopicProcess: TypeAlias = "abc.Callable[[int, JsonType], Any]"
# Values
MAX_INT = sys.maxsize
MAX_EXTRA_MINUTES = 15
BASE_TOPICS = 2
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
LOGGING_LEVELS = {
    0: logging.ERROR,
    1: logging.WARNING,
    2: logging.INFO,
    3: CALL,
    4: logging.DEBUG,
}
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
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
    )
    MOBILE_WEB = ClientInfo(
        URL("https://m.twitch.tv"),
        "r8s4dac0uhzifbpu9sjdiwzctle17ff",
        [
            # Chrome versioning is done fully on android only,
            # other platforms only use the major version
            (
                "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.7204.158 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 16; SM-A205U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.7204.158 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 16; SM-A102U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.7204.158 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 16; SM-G960U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.7204.158 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 16; SM-N960U) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.7204.158 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 16; LM-Q720) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.7204.158 Mobile Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Linux; Android 16; LM-X420) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.7204.158 Mobile Safari/537.36"
            ),
        ]
    )
    ANDROID_APP = ClientInfo(
        URL("https://www.twitch.tv"),
        "kd1unb4b3q4t58fwlpcbzcbnm76a8fp",
        [
            (
                "Dalvik/2.1.0 (Linux; U; Android 16; SM-S911B Build/TP1A.220624.014) "
                "tv.twitch.android.app/25.3.0/2503006"
            ),
            (
                "Dalvik/2.1.0 (Linux; U; Android 16; SM-S938B Build/BP2A.250605.031) "
                "tv.twitch.android.app/25.3.0/2503006"
            ),
            (
                "Dalvik/2.1.0 (Linux; Android 16; SM-X716N Build/UP1A.231005.007) "
                "tv.twitch.android.app/25.3.0/2503006"
            ),
            (
                "Dalvik/2.1.0 (Linux; U; Android 15; SM-G990B Build/AP3A.240905.015.A2) "
                "tv.twitch.android.app/25.3.0/2503006"
            ),
            (
                "Dalvik/2.1.0 (Linux; U; Android 15; SM-G970F Build/AP3A.241105.008) "
                "tv.twitch.android.app/25.3.0/2503006"
            ),
            (
                "Dalvik/2.1.0 (Linux; U; Android 15; SM-A566E Build/AP3A.240905.015.A2) "
                "tv.twitch.android.app/25.3.0/2503006"
            ),
            (
                "Dalvik/2.1.0 (Linux; U; Android 14; SM-X306B Build/UP1A.231005.007) "
                "tv.twitch.android.app/25.3.0/2503006"
            ),
        ]
    )
    SMARTBOX = ClientInfo(
        URL("https://android.tv.twitch.tv"),
        "ue6666qo983tsx6so1t0vnawi233wa",
        (
            "Mozilla/5.0 (Linux; Android 7.1; Smart Box C1) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
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


class PriorityMode(Enum):
    PRIORITY_ONLY = 0
    ENDING_SOONEST = 1
    LOW_AVBL_FIRST = 2


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
        "198492e0857f6aedead9665c81c5a06d67b25b58034649687124083ff288597d",
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
        "374314de591e69925fce3ddc2bcf085796f56ebb8cad67a0daa3165c03adc345",
        variables={
            "channelLogin": ...,  # channel login
        },
    ),
    # returns all in-progress campaigns
    "Inventory": GQLOperation(
        "Inventory",
        "d86775d0ef16a63a33ad52e80eaff963b2d5b72fada7c991504a57496e1d8e4b",
        variables={
            "fetchRewardCampaigns": False,
        }
    ),
    # returns current state of drops (current drop progress)
    "CurrentDrop": GQLOperation(
        "DropCurrentSessionContext",
        "4d06b702d25d652afb9ef835d2a550031f1cf762b193523a92166f40ea3d142b",
        variables={
            "channelID": ...,  # watched channel ID as a str
            "channelLogin": "",  # always empty string
        },
    ),
    # returns all available campaigns
    "Campaigns": GQLOperation(
        "ViewerDropsDashboard",
        "5a4da2ab3d5b47c9f9ce864e727b2cb346af1e3ea8b897fe8f704a97ff017619",
        variables={
            "fetchRewardCampaigns": False,
        }
    ),
    # returns extended information about a particular campaign
    "CampaignDetails": GQLOperation(
        "DropCampaignDetails",
        "039277bf98f3130929262cc7c6efd9c141ca3749cb6dca442fc8ead9a53f77c1",
        variables={
            "channelLogin": ...,  # user login
            "dropID": ...,  # campaign ID
        },
    ),
    # returns drops available for a particular channel
    "AvailableDrops": GQLOperation(
        "DropsHighlightService_AvailableDrops",
        "9a62a09bce5b53e26e64a671e530bc599cb6aab1e5ba3cbd5d85966d3940716f",
        variables={
            "channelID": ...,  # channel ID as a str
        },
    ),
    # retuns stream playback access token
    "PlaybackAccessToken": GQLOperation(
        "PlaybackAccessToken",
        "ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9",
        variables={
            "isLive": True,
            "isVod": False,
            "login": ...,  # channel login
            "platform": "web",
            "playerType": "site",
            "vodID": "",
        },
    ),
    # returns live channels for a particular game
    "GameDirectory": GQLOperation(
        "DirectoryPage_Game",
        "98a996c3c3ebb1ba4fd65d6671c6028d7ee8d615cb540b0731b3db2a911d3649",
        variables={
            "limit": 30,  # limit of channels returned
            "slug": ...,  # game slug
            "imageWidth": 50,
            "includeCostreaming": False,
            "options": {
                "broadcasterLanguages": [],
                "freeformTags": None,
                "includeRestricted": ["SUB_ONLY_LIVE"],
                "recommendationsContext": {"platform": "web"},
                "sort": "RELEVANCE",  # also accepted: "VIEWER_COUNT"
                "systemFilters": [],
                "tags": [],
                "requestID": "JIRA-VXP-2397",
            },
            "sortTypeIsRecency": False,
        },
    ),
    "SlugRedirect": GQLOperation(  # can be used to turn game name -> game slug
        "DirectoryGameRedirect",
        "1f0300090caceec51f33c5e20647aceff9017f740f223c3c532ba6fa59f6b6cc",
        variables={
            "name": ...,  # game name
        },
    ),
    "NotificationsView": GQLOperation(  # unused, triggers notifications "update-summary"
        "OnsiteNotifications_View",
        "e8e06193f8df73d04a1260df318585d1bd7a7bb447afa058e52095513f2bfa4f",
        variables={
            "input": {},
        },
    ),
    "NotificationsList": GQLOperation(  # unused
        "OnsiteNotifications_ListNotifications",
        "11cdb54a2706c2c0b2969769907675680f02a6e77d8afe79a749180ad16bfea6",
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
