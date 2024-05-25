from __future__ import annotations

from collections import abc
from typing import Any, TypedDict, TYPE_CHECKING

from exceptions import MinerException
from utils import json_load, json_save
from constants import IS_PACKAGED, LANG_PATH, DEFAULT_LANG

if TYPE_CHECKING:
    from typing_extensions import NotRequired


class StatusMessages(TypedDict):
    terminated: str
    watching: str
    goes_online: str
    goes_offline: str
    claimed_drop: str
    claimed_points: str
    earned_points: str
    no_channel: str
    no_campaign: str


class ChromeMessages(TypedDict):
    startup: str
    login_to_complete: str
    no_token: str
    closed_window: str


class LoginMessages(TypedDict):
    chrome: ChromeMessages
    error_code: str
    unexpected_content: str
    email_code_required: str
    twofa_code_required: str
    incorrect_login_pass: str
    incorrect_email_code: str
    incorrect_twofa_code: str


class ErrorMessages(TypedDict):
    captcha: str
    no_connection: str
    site_down: str


class GUIStatus(TypedDict):
    name: str
    idle: str
    exiting: str
    terminated: str
    cleanup: str
    gathering: str
    switching: str
    fetching_inventory: str
    fetching_campaigns: str
    adding_campaigns: str


class GUITabs(TypedDict):
    main: str
    inventory: str
    settings: str
    help: str


class GUITray(TypedDict):
    notification_title: str
    minimize: str
    show: str
    quit: str


class GUILoginForm(TypedDict):
    name: str
    labels: str
    logging_in: str
    logged_in: str
    logged_out: str
    request: str
    required: str
    username: str
    password: str
    twofa_code: str
    button: str


class GUIWebsocket(TypedDict):
    name: str
    websocket: str
    initializing: str
    connected: str
    disconnected: str
    connecting: str
    disconnecting: str
    reconnecting: str


class GUIProgress(TypedDict):
    name: str
    drop: str
    game: str
    campaign: str
    remaining: str
    drop_progress: str
    campaign_progress: str


class GUIChannelHeadings(TypedDict):
    channel: str
    status: str
    game: str
    points: str
    viewers: str


class GUIChannels(TypedDict):
    name: str
    switch: str
    load_points: str
    online: str
    pending: str
    offline: str
    headings: GUIChannelHeadings


class GUIInvFilter(TypedDict):
    name: str
    show: str
    not_linked: str
    upcoming: str
    expired: str
    excluded: str
    finished: str
    refresh: str


class GUIInvStatus(TypedDict):
    linked: str
    not_linked: str
    active: str
    expired: str
    upcoming: str
    claimed: str
    ready_to_claim: str


class GUIInventory(TypedDict):
    filter: GUIInvFilter
    status: GUIInvStatus
    starts: str
    ends: str
    allowed_channels: str
    all_channels: str
    and_more: str
    percent_progress: str
    minutes_progress: str


class GUISettingsGeneral(TypedDict):
    name: str
    autostart: str
    tray: str
    tray_notifications: str
    priority_only: str
    prioritze_end: str
    proxy: str


class GUISettings(TypedDict):
    general: GUISettingsGeneral
    game_name: str
    priority: str
    exclude: str
    reload: str
    reload_text: str


class GUIHelpLinks(TypedDict):
    name: str
    inventory: str
    campaigns: str


class GUIHelp(TypedDict):
    links: GUIHelpLinks
    how_it_works: str
    how_it_works_text: str
    getting_started: str
    getting_started_text: str


class GUIMessages(TypedDict):
    output: str
    status: GUIStatus
    tabs: GUITabs
    tray: GUITray
    login: GUILoginForm
    websocket: GUIWebsocket
    progress: GUIProgress
    channels: GUIChannels
    inventory: GUIInventory
    settings: GUISettings
    help: GUIHelp


class Translation(TypedDict):
    language_name: NotRequired[str]
    english_name: str
    status: StatusMessages
    login: LoginMessages
    error: ErrorMessages
    gui: GUIMessages


default_translation: Translation = {
    "english_name": "English",
    "status": {
        "terminated": "\nApplication Terminated.\nClose the window to exit the application.",
        "watching": "Watching: {channel}",
        "goes_online": "{channel} goes ONLINE, switching...",
        "goes_offline": "{channel} goes OFFLINE, switching...",
        "claimed_drop": "Claimed drop: {drop}",
        "claimed_points": "Claimed bonus points: {points}",
        "earned_points": "Earned points for watching: {points}, total: {balance}",
        "no_channel": "No available channels to watch. Waiting for an ONLINE channel...",
        "no_campaign": "No active campaigns to mine drops for. Waiting for an active campaign...",
    },
    "login": {
        "unexpected_content": (
            "Unexpected content type returned, usually due to being redirected. "
            "Do you need to login for internet access?"
        ),
        "chrome": {
            "startup": "Opening Chrome...",
            "login_to_complete": (
                "Complete the login procedure manually by pressing the Login button again."
            ),
            "no_token": "No authorization token could be found.",
            "closed_window": (
                "Chrome window was closed before the login procedure could complete."
            ),
        },
        "error_code": "Login error code: {error_code}",
        "incorrect_login_pass": "Incorrect username or password.",
        "incorrect_email_code": "Incorrect email code.",
        "incorrect_twofa_code": "Incorrect 2FA code.",
        "email_code_required": "Email code required. Check your email.",
        "twofa_code_required": "2FA token required.",
    },
    "error": {
        "captcha": "Your login attempt was denied by CAPTCHA.\nPlease try again in 12+ hours.",
        "site_down": "Twitch is down, retrying in {seconds} seconds...",
        "no_connection": "Cannot connect to Twitch, retrying in {seconds} seconds...",
    },
    "gui": {
        "output": "Output",
        "status": {
            "name": "Status",
            "idle": "Idle",
            "exiting": "Exiting...",
            "terminated": "Terminated",
            "cleanup": "Cleaning up channels...",
            "gathering": "Gathering channels...",
            "switching": "Switching the channel...",
            "fetching_inventory": "Fetching inventory...",
            "fetching_campaigns": "Fetching campaigns...",
            "adding_campaigns": "Adding campaigns to inventory... {counter}",
        },
        "tabs": {
            "main": "Main",
            "inventory": "Inventory",
            "settings": "Settings",
            "help": "Help",
        },
        "tray": {
            "notification_title": "Mined Drop",
            "minimize": "Minimize to Tray",
            "show": "Show",
            "quit": "Quit",
        },
        "login": {
            "name": "Login Form",
            "labels": "Status:\nUser ID:",
            "logged_in": "Logged in",
            "logged_out": "Logged out",
            "logging_in": "Logging in...",
            "required": "Login required",
            "request": "Please log in to continue.",
            "username": "Username",
            "password": "Password",
            "twofa_code": "2FA code (optional)",
            "button": "Login",
        },
        "websocket": {
            "name": "Websocket Status",
            "websocket": "Websocket #{id}:",
            "initializing": "Initializing...",
            "connected": "Connected",
            "disconnected": "Disconnected",
            "connecting": "Connecting...",
            "disconnecting": "Disconnecting...",
            "reconnecting": "Reconnecting...",
        },
        "progress": {
            "name": "Campaign Progress",
            "drop": "Drop:",
            "game": "Game:",
            "campaign": "Campaign:",
            "remaining": "{time} remaining",
            "drop_progress": "Progress:",
            "campaign_progress": "Progress:",
        },
        "channels": {
            "name": "Channels",
            "switch": "Switch",
            "load_points": "Load Points",
            "online": "ONLINE  ✔",
            "pending": "OFFLINE ⏳",
            "offline": "OFFLINE ❌",
            "headings": {
                "channel": "Channel",
                "status": "Status",
                "game": "Game",
                "viewers": "Viewers",
                "points": "Points",
            },
        },
        "inventory": {
            "filter": {
                "name": "Filter",
                "show": "Show:",
                "not_linked": "Not linked",
                "upcoming": "Upcoming",
                "expired": "Expired",
                "excluded": "Excluded",
                "finished": "Finished",
                "refresh": "Refresh",
            },
            "status": {
                "linked": "Linked ✔",
                "not_linked": "Not Linked ❌",
                "active": "Active ✔",
                "upcoming": "Upcoming ⏳",
                "expired": "Expired ❌",
                "claimed": "Claimed ✔",
                "ready_to_claim": "Ready to claim ⏳",
            },
            "starts": "Starts: {time}",
            "ends": "Ends: {time}",
            "allowed_channels": "Allowed Channels:",
            "all_channels": "All",
            "and_more": "and {amount} more...",
            "percent_progress": "{percent} of {minutes} minutes",
            "minutes_progress": "{minutes} minutes",
        },
        "settings": {
            "general": {
                "name": "General",
                "dark_theme": "Dark theme: ",
                "autostart": "Autostart: ",
                "tray": "Autostart into tray: ",
                "tray_notifications": "Tray notifications: ",
                "priority_only": "Priority Only: ",
                "prioritze_end": "Prioritize by ending soonest: ",
                "proxy": "Proxy (requires restart):",
            },
            "game_name": "Game name",
            "priority": "Priority",
            "exclude": "Exclude",
            "reload": "Reload",
            "reload_text": "Most changes require a reload to take an immediate effect: ",
        },
        "help": {
            "links": {
                "name": "Useful Links",
                "inventory": "See Twitch inventory",
                "campaigns": "See all campaigns and manage account links",
            },
            "how_it_works": "How It Works",
            "how_it_works_text": (
                "Every ~20 seconds, the application asks Twitch for a URL to the raw stream data of the channel currently being watched. "
                "It then fetches the metadata of this data stream - this is enough "
                "to advance the drops. Note that this completely bypasses the need to download "
                "any actual stream video and sound. "
                "To keep the status (ONLINE or OFFLINE) of the channels up-to-date, "
                "there's a websocket connection estabilished that receives events about streams "
                "going up or down, or updates regarding the current amount of viewers."
            ),
            "getting_started": "Getting Started",
            "getting_started_text": (
                "1. Login into the application.\n"
                "2. Ensure your Twitch account is linked to all campaigns "
                "you're interested in mining.\n"
                "3. If you're interested in just mining everything, "
                "uncheck \"Priority only\" and press on \"Reload\".\n"
                "4. If you want to mine specific games first, use the \"Priority\" list "
                "to setup an ordered list of games of your choice. Games from the top of the list "
                "will be attempted to be mined first, before the ones lower down the list.\n"
                "5. Keep the \"Priority only\" option checked, to avoid mining games "
                "that are not on the priority list. Or not - it's up to you.\n"
                "6. Use the \"Exclude\" list to tell the application "
                "which games should never be mined.\n"
                "7. Changing the contents of either of the lists, or changing the state "
                "of the \"Priority only\" option, requires you to press on \"Reload\" "
                "for the changes to take an effect."
            ),
        },
    },
}


class Translator:
    def __init__(self) -> None:
        self._langs: list[str] = []
        # start with (and always copy) the default translation
        self._translation: Translation = default_translation.copy()
        # if we're in dev, update the template English.json file
        if not IS_PACKAGED:
            default_langpath = LANG_PATH.joinpath(f"{DEFAULT_LANG}.json")
            json_save(default_langpath, default_translation)
        self._translation["language_name"] = DEFAULT_LANG
        # load available translation names
        for filepath in LANG_PATH.glob("*.json"):
            self._langs.append(filepath.stem)
        self._langs.sort()
        if DEFAULT_LANG in self._langs:
            self._langs.remove(DEFAULT_LANG)
        self._langs.insert(0, DEFAULT_LANG)

    @property
    def languages(self) -> abc.Iterable[str]:
        return iter(self._langs)

    @property
    def current(self) -> str:
        return self._translation["language_name"]

    def set_language(self, language: str):
        if language not in self._langs:
            raise ValueError("Unrecognized language")
        elif self._translation["language_name"] == language:
            # same language as loaded selected
            return
        elif language == DEFAULT_LANG:
            # default language selected - use the memory value
            self._translation = default_translation.copy()
        else:
            self._translation = json_load(
                LANG_PATH.joinpath(f"{language}.json"), default_translation
            )
            if "language_name" in self._translation:
                raise ValueError("Translations cannot define 'language_name'")
        self._translation["language_name"] = language

    def __call__(self, *path: str) -> str:
        if not path:
            raise ValueError("Language path expected")
        v: Any = self._translation
        try:
            for key in path:
                v = v[key]
        except KeyError:
            # this can only really happen for the default translation
            raise MinerException(
                f"{self.current} translation is missing the '{' -> '.join(path)}' translation key"
            )
        return v


_ = Translator()
