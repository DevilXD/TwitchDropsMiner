from __future__ import annotations

import sys
import json
import ctypes
import random
import asyncio
import logging
from time import time
from copy import deepcopy
from itertools import chain
from functools import partial
from collections import abc, deque, OrderedDict
from datetime import datetime, timedelta, timezone
from contextlib import suppress, asynccontextmanager
from typing import Any, Literal, Final, NoReturn, overload, cast, TYPE_CHECKING

import aiohttp
from yarl import URL

from translate import _
from gui import GUIManager
from channel import Channel
from websocket import WebsocketPool
from inventory import DropsCampaign
from exceptions import (
    ExitRequest,
    GQLException,
    ReloadRequest,
    LoginException,
    MinerException,
    RequestInvalid,
    CaptchaRequired,
    RequestException,
)
from utils import (
    CHARS_HEX_LOWER,
    chunk,
    timestamp,
    create_nonce,
    task_wrapper,
    RateLimiter,
    AwaitableValue,
    ExponentialBackoff,
)
from constants import (
    CALL,
    MAX_INT,
    DUMP_PATH,
    COOKIES_PATH,
    MAX_CHANNELS,
    GQL_QUERIES,
    WATCH_INTERVAL,
    State,
    ClientType,
    PriorityMode,
    WebsocketTopic,
)

if TYPE_CHECKING:
    from utils import Game
    from gui import LoginForm
    from channel import Stream
    from settings import Settings
    from inventory import BaseDrop, TimedDrop
    from constants import ClientInfo, JsonType, GQLOperation


logger = logging.getLogger("TwitchDrops")
gql_logger = logging.getLogger("TwitchDrops.gql")


class SkipExtraJsonDecoder(json.JSONDecoder):
    def decode(self, s: str, _w: Any = None) -> Any:
        # skip whitespace check
        obj, end = self.raw_decode(s)
        return obj


SAFE_LOADS = lambda s: json.loads(s, cls=SkipExtraJsonDecoder)


class _AuthState:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._lock = asyncio.Lock()
        self._logged_in = asyncio.Event()
        self.user_id: int
        self.device_id: str
        self.session_id: str
        self.access_token: str
        self.client_version: str

    def _hasattrs(self, *attrs: str) -> bool:
        return all(hasattr(self, attr) for attr in attrs)

    def _delattrs(self, *attrs: str) -> None:
        for attr in attrs:
            if hasattr(self, attr):
                delattr(self, attr)

    def invalidate(self, *, delete_cookies: bool = False) -> None:
        self._delattrs("access_token", "user_id")
        self._logged_in.clear()
        self._twitch.gui.help._invalidate_button.config(state="disabled")
        if delete_cookies:
            session = self._twitch._session
            if session is not None:
                jar = cast(aiohttp.CookieJar, session.cookie_jar)
                jar.clear()
                COOKIES_PATH.unlink(missing_ok=True)

    def clear(self) -> None:
        self._delattrs(
            "user_id",
            "device_id",
            "session_id",
            "access_token",
            "client_version",
        )
        self._logged_in.clear()
        self._twitch.gui.help._invalidate_button.config(state="disabled")

    async def _oauth_login(self) -> str:
        login_form: LoginForm = self._twitch.gui.login
        client_info: ClientInfo = self._twitch._client_type
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US",
            "Cache-Control": "no-cache",
            "Client-Id": client_info.CLIENT_ID,
            "Host": "id.twitch.tv",
            "Origin": str(client_info.CLIENT_URL),
            "Pragma": "no-cache",
            "Referer": str(client_info.CLIENT_URL),
            "User-Agent": client_info.USER_AGENT,
            "X-Device-Id": self.device_id,
        }
        payload = {
            "client_id": client_info.CLIENT_ID,
            "scopes": "",  # no scopes needed
        }
        while True:
            try:
                now = datetime.now(timezone.utc)
                async with self._twitch.request(
                    "POST", "https://id.twitch.tv/oauth2/device", headers=headers, data=payload
                ) as response:
                    # {
                    #     "device_code": "40 chars [A-Za-z0-9]",
                    #     "expires_in": 1800,
                    #     "interval": 5,
                    #     "user_code": "8 chars [A-Z]",
                    #     "verification_uri": "https://www.twitch.tv/activate?device-code=ABCDEFGH"
                    # }
                    response_json: JsonType = await response.json()
                    required_fields = (
                        "device_code",
                        "user_code",
                        "interval",
                        "verification_uri",
                        "expires_in",
                    )
                    missing_fields = [
                        field for field in required_fields if field not in response_json
                    ]
                    if response.status != 200 or missing_fields:
                        # Twitch returns an error JSON (for example {"error": "invalid client"})
                        # when a client is no longer eligible for device authorization. Do not
                        # turn that into an opaque KeyError: surface a useful login error instead.
                        error_detail = cast(
                            str,
                            response_json.get("message")
                            or response_json.get("error")
                            or f"HTTP {response.status}",
                        )
                        raise LoginException(
                            f"Twitch device authorization failed: {error_detail}"
                        )
                    device_code: str = cast(str, response_json["device_code"])
                    user_code: str = cast(str, response_json["user_code"])
                    interval: int = int(response_json["interval"])
                    verification_uri: URL = URL(cast(str, response_json["verification_uri"]))
                    expires_at = now + timedelta(seconds=int(response_json["expires_in"]))

                # Print the code to the user, open them the activate page so they can type it in
                await login_form.ask_enter_code(verification_uri, user_code)

                payload = {
                    "client_id": self._twitch._client_type.CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                }
                while True:
                    # sleep first, not like the user is gonna enter the code *that* fast
                    await asyncio.sleep(interval)
                    async with self._twitch.request(
                        "POST",
                        "https://id.twitch.tv/oauth2/token",
                        headers=headers,
                        data=payload,
                        invalidate_after=expires_at,
                    ) as response:
                        # 200 means success, 400 means the user haven't entered the code yet
                        if response.status != 200:
                            continue
                        response_json = await response.json()
                        # {
                        #     "access_token": "40 chars [A-Za-z0-9]",
                        #     "refresh_token": "40 chars [A-Za-z0-9]",
                        #     "scope": [...],
                        #     "token_type": "bearer"
                        # }
                        self.access_token = cast(str, response_json["access_token"])
                        return self.access_token
            except RequestInvalid:
                # the device_code has expired, request a new code
                continue

    async def _login(self) -> str:
        logger.info("Login flow started")
        gui_print = self._twitch.gui.print
        login_form: LoginForm = self._twitch.gui.login
        client_info: ClientInfo = self._twitch._client_type

        token_kind: str = ''
        use_chrome: bool = False
        payload: JsonType = {
            # username and password are added later
            # "username": str,
            # "password": str,
            # client ID to-be associated with the access token
            "client_id": client_info.CLIENT_ID,
            "undelete_user": False,  # purpose unknown
            "remember_me": True,  # persist the session via the cookie
            # "authy_token": str,  # 2FA token
            # "twitchguard_code": str,  # email code
            # "captcha": str,  # self-fed captcha
            # 'force_twitchguard': False,  # force email code confirmation
        }

        while True:
            login_data = await login_form.ask_login()
            payload["username"] = login_data.username
            payload["password"] = login_data.password
            # reinstate the 2FA token, if present
            payload.pop("authy_token", None)
            payload.pop("twitchguard_code", None)
            if login_data.token:
                # if there's no token kind set yet, and the user has entered a token,
                # we can immediately assume it's an authenticator token and not an email one
                if not token_kind:
                    token_kind = "authy"
                if token_kind == "authy":
                    payload["authy_token"] = login_data.token
                elif token_kind == "email":
                    payload["twitchguard_code"] = login_data.token

            # use fancy headers to mimic the twitch android app
            headers = {
                "Accept": "application/vnd.twitchtv.v3+json",
                "Accept-Encoding": "gzip",
                "Accept-Language": "en-US",
                "Client-Id": client_info.CLIENT_ID,
                "Content-Type": "application/json; charset=UTF-8",
                "Host": "passport.twitch.tv",
                "User-Agent": client_info.USER_AGENT,
                "X-Device-Id": self.device_id,
                # "X-Device-Id": ''.join(random.choices('0123456789abcdef', k=32)),
            }
            async with self._twitch.request(
                "POST", "https://passport.twitch.tv/login", headers=headers, json=payload
            ) as response:
                login_response: JsonType = await response.json(loads=SAFE_LOADS)

            # Feed this back in to avoid running into CAPTCHA if possible
            if "captcha_proof" in login_response:
                payload["captcha"] = {"proof": login_response["captcha_proof"]}

            # Error handling
            if "error_code" in login_response:
                error_code: int = login_response["error_code"]
                logger.info(f"Login error code: {error_code}")
                if error_code == 1000:
                    logger.info("1000: CAPTCHA is required")
                    use_chrome = True
                    break
                elif error_code in (2004, 3001):
                    logger.info("3001: Login failed due to incorrect username or password")
                    gui_print(_("login", "incorrect_login_pass"))
                    if error_code == 2004:
                        # invalid username
                        login_form.clear(login=True)
                    login_form.clear(password=True)
                    continue
                elif error_code in (
                    3012,  # Invalid authy token
                    3023,  # Invalid email code
                ):
                    logger.info("3012/23: Login failed due to incorrect 2FA code")
                    if error_code == 3023:
                        token_kind = "email"
                        gui_print(_("login", "incorrect_email_code"))
                    else:
                        token_kind = "authy"
                        gui_print(_("login", "incorrect_twofa_code"))
                    login_form.clear(token=True)
                    continue
                elif error_code in (
                    3011,  # Authy token needed
                    3022,  # Email code needed
                ):
                    # 2FA handling
                    logger.info("3011/22: 2FA token required")
                    # user didn't provide a token, so ask them for it
                    if error_code == 3022:
                        token_kind = "email"
                        gui_print(_("login", "email_code_required"))
                    else:
                        token_kind = "authy"
                        gui_print(_("login", "twofa_code_required"))
                    continue
                elif error_code >= 5000:
                    # Special errors, usually from Twitch telling the user to "go away"
                    # We print the code out to inform the user, and just use chrome flow instead
                    # {
                    #     "error_code":5023,
                    #     "error":"Please update your app to continue",
                    #     "error_description":"client is not supported for this feature"
                    # }
                    # {
                    #     "error_code":5027,
                    #     "error":"Please update your app to continue",
                    #     "error_description":"client blocked from this operation"
                    # }
                    gui_print(_("login", "error_code").format(error_code=error_code))
                    logger.info(str(login_response))
                    use_chrome = True
                    break
                else:
                    ext_msg = str(login_response)
                    logger.info(ext_msg)
                    raise LoginException(ext_msg)
            # Success handling
            if "access_token" in login_response:
                self.access_token = cast(str, login_response["access_token"])
                logger.info("Access token granted")
                login_form.clear()
                break

        if use_chrome:
            # await self._chrome_login()
            raise CaptchaRequired()

        if hasattr(self, "access_token"):
            return self.access_token
        raise LoginException("Login flow finished without setting the access token")

    def headers(self, *, user_agent: str = '', gql: bool = False) -> JsonType:
        client_info: ClientInfo = self._twitch._client_type
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Client-Id": client_info.CLIENT_ID,
        }
        if user_agent:
            headers["User-Agent"] = user_agent
        if hasattr(self, "session_id"):
            headers["Client-Session-Id"] = self.session_id
        # if hasattr(self, "client_version"):
            # headers["Client-Version"] = self.client_version
        if hasattr(self, "device_id"):
            headers["X-Device-Id"] = self.device_id
        if gql:
            headers["Origin"] = str(client_info.CLIENT_URL)
            headers["Referer"] = str(client_info.CLIENT_URL)
            headers["Authorization"] = f"OAuth {self.access_token}"
        return headers

    async def validate(self):
        async with self._lock:
            await self._validate()

    async def _validate(self):
        if not hasattr(self, "session_id"):
            self.session_id = create_nonce(CHARS_HEX_LOWER, 16)
        if not self._hasattrs("device_id", "access_token", "user_id"):
            session = await self._twitch.get_session()
            jar = cast(aiohttp.CookieJar, session.cookie_jar)
            client_info: ClientInfo = self._twitch._client_type
            if not self._hasattrs("device_id"):
                async with self._twitch.request(
                    "GET", client_info.CLIENT_URL, headers=self.headers()
                ) as response:
                    page_html = await response.text("utf8")
                    assert page_html is not None
                #     match = re.search(r'twilightBuildID="([-a-z0-9]+)"', page_html)
                # if match is None:
                #     raise MinerException("Unable to extract client_version")
                # self.client_version = match.group(1)
                # doing the request ends up setting the "unique_id" value in the cookie
                cookie = jar.filter_cookies(client_info.CLIENT_URL)
                self.device_id = cookie["unique_id"].value
            if not self._hasattrs("access_token", "user_id"):
                # looks like we're missing something
                login_form: LoginForm = self._twitch.gui.login
                logger.info("Checking login")
                login_form.update(_("gui", "login", "logging_in"), None)
                validate_response: JsonType = {}
                cookie = jar.filter_cookies(client_info.CLIENT_URL)
                for client_mismatch_attempt in range(2):
                    for invalid_token_attempt in range(2):
                        cookie = jar.filter_cookies(client_info.CLIENT_URL)
                        if "auth-token" not in cookie:
                            self.access_token = await self._oauth_login()
                            cookie["auth-token"] = self.access_token
                        elif not hasattr(self, "access_token"):
                            logger.info("Restoring session from cookie")
                            self.access_token = cookie["auth-token"].value
                        # validate the auth token, by obtaining user_id
                        async with self._twitch.request(
                            "GET",
                            "https://id.twitch.tv/oauth2/validate",
                            headers={"Authorization": f"OAuth {self.access_token}"}
                        ) as response:
                            if response.status == 401:
                                # the access token we have is invalid - clear the cookie and reauth
                                logger.info("Restored session is invalid")
                                assert client_info.CLIENT_URL.host is not None
                                jar.clear_domain(client_info.CLIENT_URL.host)
                                continue
                            elif response.status == 200:
                                validate_response = await response.json()
                                break
                    else:
                        raise RuntimeError("Login verification failure (step #2)")
                    # ensure the cookie's client ID matches the currently selected client
                    if validate_response["client_id"] == client_info.CLIENT_ID:
                        break
                    # otherwise, we need to delete the entire cookie file and clear the jar
                    logger.info("Cookie client ID mismatch")
                    jar.clear()
                    COOKIES_PATH.unlink(missing_ok=True)
                else:
                    raise RuntimeError("Login verification failure (step #1)")
                self.user_id = int(validate_response["user_id"])
                cookie["persistent"] = str(self.user_id)
                logger.info(f"Login successful, user ID: {self.user_id}")
                login_form.update(_("gui", "login", "logged_in"), self.user_id)
                # update our cookie and save it
                jar.update_cookies(cookie, client_info.CLIENT_URL)
                jar.save(COOKIES_PATH)
        self._twitch.gui.help._invalidate_button.config(state="normal")
        self._logged_in.set()


class Twitch:
    def __init__(self, settings: Settings):
        self.settings: Settings = settings
        # State management
        self._state: State = State.IDLE
        self._state_change = asyncio.Event()
        self.wanted_games: list[Game] = []
        self.inventory: list[DropsCampaign] = []
        self._drops: dict[str, TimedDrop] = {}
        self._campaigns: dict[str, DropsCampaign] = {}
        self._mnt_triggers: deque[datetime] = deque()
        # NOTE: GQL is pretty volatile and breaks everything if one runs into their rate limit.
        # Do not modify the default, safe values.
        self._qgl_limiter = RateLimiter(capacity=5, window=1)
        # Client type, session and auth
        # Twitch stopped issuing device codes to the Android app client in September 2026.
        # Use the Smart Box client for the device authorization flow; this mirrors the
        # upstream v1.3.1 login fix and prevents fresh installs from failing before the
        # browser activation page can be opened.
        self._client_type: ClientInfo = ClientType.SMARTBOX
        self._session: aiohttp.ClientSession | None = None
        self._auth_state: _AuthState = _AuthState(self)
        # GUI
        self.gui = GUIManager(self)
        # Storing and watching channels
        self.channels: OrderedDict[int, Channel] = OrderedDict()
        self.watching_channel: AwaitableValue[Channel] = AwaitableValue()
        self._watching_task: asyncio.Task[None] | None = None
        self._watching_restart = asyncio.Event()
        # Websocket
        self.websocket = WebsocketPool(self)
        # Maintenance task
        self._mnt_task: asyncio.Task[None] | None = None
        # Channels temporarily deprioritized because watch progress stalled (channel_id -> stall_timestamp).
        self._stalled_channels: dict[int, float] = {}
        self._no_progress_count: int = 0
        self._last_progress_time: float = 0.0
        # Session stats & finish action state
        self._session_minutes_watched: int = 0
        self._session_drops_claimed: int = 0
        self._finish_action_triggered: bool = False

    def is_stalled(self, channel_id: int, cooldown_seconds: float = 1800.0) -> bool:
        """
        Check if a channel is on stall cooldown. Defaults to 30 minutes.
        """
        if channel_id not in self._stalled_channels:
            return False
        if time() - self._stalled_channels[channel_id] > cooldown_seconds:
            del self._stalled_channels[channel_id]
            return False
        return True

    def mark_stalled(self, channel_id: int) -> None:
        """
        Mark a channel as stalled with the current timestamp.
        """
        self._stalled_channels[channel_id] = time()

    def clear_stalled(self, channel_id: int) -> None:
        """
        Remove a channel from the stalled dictionary.
        """
        self._stalled_channels.pop(channel_id, None)

    def on_drop_claimed(self, drop: BaseDrop) -> None:
        """
        Record a claimed drop in the current session, update GUI stats, and trigger Discord webhook if configured.
        """
        self._session_drops_claimed += 1
        self.gui.progress.update_stats(
            self._session_drops_claimed, self._session_minutes_watched
        )
        webhook_url = self.settings.discord_webhook.strip()
        if webhook_url:
            asyncio.create_task(self.send_discord_drop_claimed(drop, webhook_url))

    async def send_discord_drop_claimed(self, drop: BaseDrop, webhook_url: str) -> None:
        """
        Send a clean Discord webhook embed when a drop is claimed.
        """
        campaign = drop.campaign
        claimed_count = sum(1 for d in campaign.drops if d.is_claimed)
        total_count = len(campaign.drops)
        embed: dict[str, Any] = {
            "title": f"Drop Claimed: {drop.name}",
            "color": 0x9146FF,
            "fields": [
                {"name": "Game", "value": str(campaign.game), "inline": True},
                {
                    "name": "Campaign Progress",
                    "value": f"{claimed_count} / {total_count} drops claimed ({campaign.name})",
                    "inline": True,
                },
            ],
            "footer": {"text": "Twitch Drops Miner"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if drop.benefits and drop.benefits[0].image_url:
            embed["thumbnail"] = {"url": str(drop.benefits[0].image_url)}
        payload = {"embeds": [embed]}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(f"Discord webhook returned HTTP {resp.status}")
        except Exception as exc:
            logger.warning(f"Failed to send Discord webhook notification: {exc}")

    @task_wrapper
    async def send_discord_test(self, webhook_url: str) -> None:
        """
        Send a test embed to the configured Discord webhook URL.
        """
        embed: dict[str, Any] = {
            "title": "Twitch Drops Miner — Webhook Connected",
            "description": "Drop claim notifications will be posted to this channel.",
            "color": 0x9146FF,
            "fields": [
                {
                    "name": "Session Status",
                    "value": (
                        f"{self._session_drops_claimed} drops claimed | "
                        f"{self._session_minutes_watched} mins mined"
                    ),
                    "inline": False,
                }
            ],
            "footer": {"text": "Twitch Drops Miner"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json={"embeds": [embed]},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status < 300:
                        self.print("Discord webhook test message sent.")
                    else:
                        self.print(f"Discord webhook test failed (HTTP {resp.status}).")
        except Exception as exc:
            self.print(f"Discord webhook test error: {exc}")

    def _check_finish_action(self) -> None:
        """
        Execute the configured finish action (1 = Exit App, 2 = Sleep PC) once all wanted
        campaigns have finished, provided at least 1 minute was mined or 1 drop was claimed
        during the current session.
        """
        action = self.settings.finish_action
        if action not in (1, 2) or self._finish_action_triggered:
            return
        if self._session_minutes_watched <= 0 and self._session_drops_claimed <= 0:
            return
        self._finish_action_triggered = True
        if action == 1:
            self.print("All wanted drops finished — exiting application (When finished: Exit App).")
            self.gui.close()
        elif action == 2:
            self.print("All wanted drops finished — putting PC to sleep (When finished: Sleep PC).")
            if sys.platform == "win32":
                with suppress(Exception):
                    ctypes.windll.PowrProf.SetSuspendState(0, 1, 0)


    async def get_session(self) -> aiohttp.ClientSession:
        if (session := self._session) is not None:
            if session.closed:
                raise RuntimeError("Session is closed")
            return session
        # load in cookies
        cookie_jar = aiohttp.CookieJar()
        try:
            if COOKIES_PATH.exists():
                cookie_jar.load(COOKIES_PATH)
        except Exception:
            # if loading in the cookies file ends up in an error, just ignore it
            # clear the jar, just in case
            cookie_jar.clear()
        # create timeouts
        # connection quality mulitiplier determines the magnitude of timeouts
        connection_quality = self.settings.connection_quality
        if connection_quality < 1:
            connection_quality = self.settings.connection_quality = 1
        elif connection_quality > 6:
            connection_quality = self.settings.connection_quality = 6
        timeout = aiohttp.ClientTimeout(
            sock_connect=5*connection_quality,
            total=10*connection_quality,
        )
        # create session, limited to 50 connections at maximum
        connector = aiohttp.TCPConnector(limit=50)
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            cookie_jar=cookie_jar,
            headers={"User-Agent": self._client_type.USER_AGENT},
        )
        return self._session

    async def shutdown(self) -> None:
        start_time = time()
        self.stop_watching()
        if self._watching_task is not None:
            self._watching_task.cancel()
            self._watching_task = None
        if self._mnt_task is not None:
            self._mnt_task.cancel()
            self._mnt_task = None
        # stop websocket, close session and save cookies
        await self.websocket.stop(clear_topics=True)
        if self._session is not None:
            cookie_jar = cast(aiohttp.CookieJar, self._session.cookie_jar)
            # clear empty cookie entries off the cookies file before saving
            # NOTE: Unfortunately, aiohttp provides no easy way of clearing empty cookies,
            # so we need to access the private '_cookies' attribute for this.
            for cookie_key, cookie in list(cookie_jar._cookies.items()):
                if not cookie:
                    del cookie_jar._cookies[cookie_key]
            cookie_jar.save(COOKIES_PATH)
            await self._session.close()
            self._session = None
        self._drops.clear()
        self._campaigns.clear()
        self.channels.clear()
        self.inventory.clear()
        self._auth_state.clear()
        self.wanted_games.clear()
        self._mnt_triggers.clear()
        self._stalled_channels.clear()
        self._no_progress_count = 0
        self._last_progress_time = 0.0
        # wait at least half a second + whatever it takes to complete the closing
        # this allows aiohttp to safely close the session
        await asyncio.sleep(max(0.0, start_time + 0.5 - time()))

    def wait_until_login(self) -> abc.Coroutine[Any, Any, Literal[True]]:
        return self._auth_state._logged_in.wait()

    def change_state(self, state: State) -> None:
        if self._state is not State.EXIT:
            # prevent state changing once we switch to exit state
            self._state = state
        self._state_change.set()

    def state_change(self, state: State) -> abc.Callable[[], None]:
        # this is identical to change_state, but defers the call
        # perfect for GUI usage
        return partial(self.change_state, state)

    def close(self):
        """
        Called when the application is requested to close by the user,
        usually by the console or application window being closed.
        """
        self.change_state(State.EXIT)

    def prevent_close(self):
        """
        Called when the application window has to be prevented from closing, even after the user
        closes it with X. Usually used solely to display tracebacks from the closing sequence.
        """
        self.gui.prevent_close()

    def print(self, message: str):
        """
        Can be used to print messages within the GUI.
        """
        self.gui.print(message)

    def save(self, *, force: bool = False) -> None:
        """
        Saves the application state.
        """
        self.gui.save(force=force)
        self.settings.save(force=force)

    def is_game_excluded(self, game: Game | None) -> bool:
        if game is None:
            return False
        exclude = self.settings.exclude
        return any(game.matches(ex) for ex in exclude)

    def get_game_priority_index(self, game: Game | None) -> int:
        if game is None:
            return MAX_INT
        priority = self.settings.priority
        for idx, item in enumerate(priority):
            if game.matches(item):
                return idx
        return MAX_INT

    def get_priority(self, channel: Channel) -> int:
        """
        Return a priority number for a given channel.

        0 has the highest priority.
        Higher numbers -> lower priority.
        MAX_INT (a really big number) signifies the lowest possible priority.
        """
        if (
            (game := channel.game) is None  # None when OFFLINE or no game set
            or game not in self.wanted_games  # we don't care about the played game
        ):
            return MAX_INT
        return self.wanted_games.index(game)

    @staticmethod
    def _viewers_key(channel: Channel) -> int:
        if (viewers := channel.viewers) is not None:
            return viewers
        return -1

    async def run(self):
        if self.settings.dump:
            with open(DUMP_PATH, 'w', encoding="utf8"):
                # replace the existing file with an empty one
                pass
        while True:
            try:
                await self._run()
                break
            except ReloadRequest:
                await self.shutdown()
            except ExitRequest:
                break
            except aiohttp.ContentTypeError as exc:
                raise RequestException(_("login", "unexpected_content")) from exc

    async def _run(self):
        """
        Main method that runs the whole client.

        Here, we manage several things, specifically:
        • Fetching the drops inventory to make sure that everything we can claim, is claimed
        • Selecting a stream to watch, and watching it
        • Changing the stream that's being watched if necessary
        """
        self.gui.start()
        auth_state = await self.get_auth()
        await self.websocket.start()
        # NOTE: watch task is explicitly restarted on each new run
        if self._watching_task is not None:
            self._watching_task.cancel()
        self._watching_task = asyncio.create_task(self._watch_loop())
        # Add default topics
        self.websocket.add_topics([
            WebsocketTopic("User", "Drops", auth_state.user_id, self.process_drops),
            WebsocketTopic(
                "User", "Notifications", auth_state.user_id, self.process_notifications
            ),
        ])
        full_cleanup: bool = False
        channels: Final[OrderedDict[int, Channel]] = self.channels
        self.change_state(State.INVENTORY_FETCH)
        while True:
            if self._state is State.IDLE:
                if self.settings.dump:
                    self.gui.close()
                    continue
                self.gui.tray.change_icon("idle")
                self.gui.status.update(_("gui", "status", "idle"))
                self.stop_watching()
                # clear the flag and wait until it's set again
                self._state_change.clear()
            elif self._state is State.INVENTORY_FETCH:
                self.gui.tray.change_icon("maint")
                # ensure the websocket is running
                await self.websocket.start()
                await self.fetch_inventory()
                self.gui.set_games(set(campaign.game for campaign in self.inventory))
                # Save state on every inventory fetch
                self.save()
                self.change_state(State.GAMES_UPDATE)
            elif self._state is State.GAMES_UPDATE:
                # claim drops from expired and active campaigns
                for campaign in self.inventory:
                    if not campaign.upcoming:
                        for drop in campaign.drops:
                            if drop.can_claim:
                                await drop.claim()
                # figure out which games we want
                self.wanted_games.clear()
                self._stalled_channels.clear()
                exclude = self.settings.exclude
                priority = self.settings.priority
                priority_mode = self.settings.priority_mode
                priority_only = priority_mode is PriorityMode.PRIORITY_ONLY
                if priority_only and not priority:
                    # A fresh install (or cleared priority list) in PRIORITY_ONLY mode has
                    # nothing eligible to watch, so the miner would otherwise sit on Idle.
                    message = (
                        "Idle — Your Priority list in Settings is empty! Go to the Settings "
                        "tab, add the games you want drops for to Priority, and click Reload."
                    )
                    self.print(message)
                    self.gui.status.update(message)
                next_hour = datetime.now(timezone.utc) + timedelta(hours=1)
                sorted_campaigns: list[DropsCampaign] = list(self.inventory)
                if not priority_only:
                    if priority_mode is PriorityMode.ENDING_SOONEST:
                        sorted_campaigns.sort(key=lambda c: c.ends_at)
                    elif priority_mode is PriorityMode.LOW_AVBL_FIRST:
                        sorted_campaigns.sort(key=lambda c: c.availability)
                sorted_campaigns.sort(
                    key=lambda c: self.get_game_priority_index(c.game)
                )
                for campaign in sorted_campaigns:
                    game: Game = campaign.game
                    is_excluded = self.is_game_excluded(game)
                    p_index = self.get_game_priority_index(game)
                    if (
                        game not in self.wanted_games  # isn't already there
                        # and isn't excluded by list or priority mode
                        and not is_excluded
                        and (not priority_only or p_index < MAX_INT)
                        # and can be progressed within the next hour
                        and campaign.can_earn_within(next_hour)
                    ):
                        # non-excluded games with no priority are placed last, below priority ones
                        self.wanted_games.append(game)
                full_cleanup = True
                self.restart_watching()
                self.change_state(State.CHANNELS_CLEANUP)
            elif self._state is State.CHANNELS_CLEANUP:
                self.gui.status.update(_("gui", "status", "cleanup"))
                if not self.wanted_games or full_cleanup:
                    # no games selected or we're doing full cleanup: remove everything
                    to_remove_channels: list[Channel] = list(channels.values())
                else:
                    # remove all channels that:
                    to_remove_channels = [
                        channel
                        for channel in channels.values()
                        if (
                            (
                                channel.game is not None
                                and self.is_game_excluded(channel.game)
                            )  # streaming an excluded game (even if ACL-based)
                            or (
                                not channel.acl_based  # aren't ACL-based
                                and (
                                    channel.offline  # and are offline
                                    # or online but aren't streaming the game we want anymore
                                    or (
                                        channel.game is None
                                        or channel.game not in self.wanted_games
                                    )
                                )
                            )
                        )
                    ]
                full_cleanup = False
                if to_remove_channels:
                    to_remove_topics: list[str] = []
                    for channel in to_remove_channels:
                        to_remove_topics.append(
                            WebsocketTopic.as_str("Channel", "StreamState", channel.id)
                        )
                        to_remove_topics.append(
                            WebsocketTopic.as_str("Channel", "StreamUpdate", channel.id)
                        )
                    self.websocket.remove_topics(to_remove_topics)
                    for channel in to_remove_channels:
                        del channels[channel.id]
                        channel.remove()
                    del to_remove_channels, to_remove_topics
                if self.wanted_games:
                    self.change_state(State.CHANNELS_FETCH)
                else:
                    # with no games available, we switch to IDLE after cleanup
                    self.print(_("status", "no_campaign"))
                    self.change_state(State.IDLE)
                    self._check_finish_action()
            elif self._state is State.CHANNELS_FETCH:
                self.gui.status.update(_("gui", "status", "gathering"))
                # Start with all current channels, but keep the live mapping intact
                # while network discovery runs. PubSub remains subscribed during this
                # phase, so clearing the mapping here creates a race where valid stream
                # events resolve as "non-existing channel".
                new_channels: set[Channel] = set(channels.values())
                # gather and add ACL channels from campaigns
                # NOTE: we consider only campaigns that can be progressed
                # NOTE: we use another set so that we can set them online separately
                no_acl: set[Game] = set()
                acl_channels: set[Channel] = set()
                next_hour = datetime.now(timezone.utc) + timedelta(hours=1)
                for campaign in self.inventory:
                    if (
                        campaign.game in self.wanted_games
                        and campaign.can_earn_within(next_hour)
                    ):
                        if campaign.allowed_channels:
                            acl_channels.update(campaign.allowed_channels)
                        else:
                            no_acl.add(campaign.game)
                # remove all ACL channels that already exist from the other set
                acl_channels.difference_update(new_channels)

                # ACL status checks and game-directory discovery are independent.
                # Run both pipelines together, and batch GameDirectory operations
                # instead of paying one HTTP round trip per eligible game.
                acl_check_task = asyncio.create_task(
                    self.bulk_check_online(acl_channels, check_available_drops=False)
                )
                directory_task = asyncio.create_task(
                    self.get_live_streams_bulk(no_acl, drops_enabled=True)
                )
                try:
                    _acl_result, directory_channels = await asyncio.gather(
                        acl_check_task,
                        directory_task,
                    )
                except (Exception, asyncio.CancelledError):
                    # gather() does not reliably cancel sibling tasks when one
                    # independently-created task fails. Stop and drain both so a
                    # failed channel refresh cannot keep mutating state in background.
                    for task in (acl_check_task, directory_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        acl_check_task,
                        directory_task,
                        return_exceptions=True,
                    )
                    raise

                # finally, add them as new channels
                new_channels.update(acl_channels)
                new_channels.update(directory_channels)
                # sort them descending by viewers, by priority and by game priority
                # NOTE: Viewers sort also ensures ONLINE channels are sorted to the top
                # NOTE: We can drop using the set now, because there's no more channels being added
                ordered_channels: list[Channel] = sorted(
                    new_channels, key=self._viewers_key, reverse=True
                )
                ordered_channels.sort(key=lambda ch: ch.is_current_acl, reverse=True)
                ordered_channels.sort(key=lambda ch: self.can_watch(ch), reverse=True)
                ordered_channels.sort(key=self.get_priority)
                # ensure that we won't end up with more channels than we can handle
                # NOTE: we trim from the end because that's where the non-priority,
                # offline (or online but low viewers) channels end up
                ordered_channels = ordered_channels[:MAX_CHANNELS]

                # Verify available drops for retained online channels (both ACL and directory)
                # discovered after MAX_CHANNELS trimming.
                if self.settings.available_drops_check:
                    await self.bulk_check_available_drops(
                        channel
                        for channel in ordered_channels
                        if channel.online
                    )

                # Atomically reconcile the discovered set with the currently tracked
                # set. All network awaits are finished above, so there is no event-loop
                # interleaving between removing stale channels and repopulating the GUI.
                desired_ids = {channel.id for channel in ordered_channels}
                to_remove_channels = [
                    channel
                    for channel_id, channel in channels.items()
                    if channel_id not in desired_ids
                ]
                if to_remove_channels:
                    to_remove_topics: list[str] = []
                    for channel in to_remove_channels:
                        to_remove_topics.append(
                            WebsocketTopic.as_str("Channel", "StreamState", channel.id)
                        )
                        to_remove_topics.append(
                            WebsocketTopic.as_str("Channel", "StreamUpdate", channel.id)
                        )
                    self.websocket.remove_topics(to_remove_topics)
                    for channel in to_remove_channels:
                        del channels[channel.id]
                        channel.remove()
                    del to_remove_topics

                # Rebuild only the visual ordering now that the authoritative channel
                # mapping is stable. Existing Channel objects remain valid throughout
                # the fetch, so queued PubSub events can still resolve correctly.
                self.gui.channels.clear()
                for channel in ordered_channels:
                    channels[channel.id] = channel
                self.gui.channels.display_many(ordered_channels)
                del desired_ids, to_remove_channels
                # subscribe to these channel's state updates
                to_add_topics: list[WebsocketTopic] = []
                for channel_id in channels:
                    to_add_topics.append(
                        WebsocketTopic(
                            "Channel", "StreamState", channel_id, self.process_stream_state
                        )
                    )
                    to_add_topics.append(
                        WebsocketTopic(
                            "Channel", "StreamUpdate", channel_id, self.process_stream_update
                        )
                    )
                self.websocket.add_topics(to_add_topics)
                # relink watching channel after cleanup,
                # or stop watching it if it no longer qualifies
                # NOTE: this replaces 'self.watching_channel's internal value with the new object
                watching_channel = self.watching_channel.get_with_default(None)
                if watching_channel is not None:
                    new_watching: Channel | None = channels.get(watching_channel.id)
                    if new_watching is not None and self.can_watch(new_watching):
                        self.watch(new_watching, update_status=False)
                    else:
                        # we've removed a channel we were watching
                        self.stop_watching()
                    del new_watching
                # pre-display the active drop with a substracted minute
                for channel in channels.values():
                    # check if there's any channels we can watch first
                    if self.can_watch(channel):
                        if (
                            (active_campaign := self.get_active_campaign(channel)) is not None
                            and (active_drop := active_campaign.first_drop) is not None
                        ):
                            active_drop.display(countdown=False, subone=True)
                        break
                self.change_state(State.CHANNEL_SWITCH)
                del (
                    no_acl,
                    acl_channels,
                    new_channels,
                    to_add_topics,
                    ordered_channels,
                    watching_channel,
                )
            elif self._state is State.CHANNEL_SWITCH:
                if self.settings.dump:
                    self.gui.close()
                    continue
                self.gui.status.update(_("gui", "status", "switching"))
                # Change into the selected channel, stay in the watching channel,
                # or select a new channel that meets the required conditions
                new_watching = None
                watching_channel = self.watching_channel.get_with_default(None)
                selected_channel = self.gui.channels.get_selection()
                if selected_channel is not None:
                    # User explicitly requested to switch to this channel
                    if watching_channel is not None and selected_channel.id == watching_channel.id:
                        msg = f"Already watching {selected_channel.name}."
                        self.print(msg)
                        self.gui.status.update(msg)
                    elif not selected_channel.online:
                        msg = f"Cannot switch to {selected_channel.name} — channel is OFFLINE."
                        logger.info(msg)
                        self.print(msg)
                        self.gui.status.update(msg)
                    elif self.is_game_excluded(selected_channel.game):
                        msg = f"Cannot switch to {selected_channel.name} — {selected_channel.game} is in your Exclude list."
                        logger.info(msg)
                        self.print(msg)
                        self.gui.status.update(msg)
                    elif self.can_watch(selected_channel):
                        self.clear_stalled(selected_channel.id)
                        new_watching = selected_channel
                    else:
                        # Channel is online but not eligible to earn drops
                        ch_game = selected_channel.game
                        game_campaigns = (
                            [c for c in self.inventory if c.game == ch_game]
                            if ch_game
                            else []
                        )
                        if not game_campaigns:
                            reason = f"no active drop campaigns for {ch_game}"
                        elif all(c.finished for c in game_campaigns):
                            reason = f"all drops for {ch_game} have already been earned and claimed"
                        else:
                            active_earnable = [
                                c for c in game_campaigns if c.active and not c.finished
                            ]
                            acl_camps = [c for c in active_earnable if c.allowed_channels]
                            if acl_camps:
                                allowed_names = ", ".join(
                                    sorted({ch.name for c in acl_camps for ch in c.allowed_channels})
                                )
                                reason = f"campaign requires official tournament/partner channels ({allowed_names})"
                            elif not selected_channel.drops_enabled:
                                reason = "streamer has drops disabled"
                            else:
                                reason = "no earnable drops available on this channel"

                        msg = f"Cannot switch to {selected_channel.name} — {reason}."
                        logger.info(msg)
                        self.print(msg)
                        self.gui.status.update(msg)

                if new_watching is None and selected_channel is None:
                    # Automatic switch selection only runs if user didn't explicitly pick a channel
                    sorted_channels = sorted(channels.values(), key=self.get_priority)
                    for channel in sorted_channels:
                        if self.should_switch(channel):
                            new_watching = channel
                            break
                    if new_watching is None and self._stalled_channels:
                        # Check if any watchable candidate's stall cooldown has expired
                        for channel in sorted_channels:
                            if self.can_watch(channel) and not self.is_stalled(channel.id):
                                new_watching = channel
                                break
                if new_watching is not None:
                    # if we have a better switch target - do so
                    self.watch(new_watching)
                    # break the state change chain by clearing the flag
                    self._state_change.clear()
                elif (
                    watching_channel is not None
                    and self.can_watch(watching_channel)
                    and not self.is_stalled(watching_channel.id)
                ):
                    # otherwise, continue watching what we had before
                    self.gui.status.update(
                        _("status", "watching").format(channel=watching_channel.name)
                    )
                    # break the state change chain by clearing the flag
                    self._state_change.clear()
                else:
                    # all channels are stalled or offline
                    message = (
                        "Idle — All current streams have stalled drop progress. "
                        "Waiting for cooldown or next channel refresh..."
                    )
                    logger.info(message)
                    self.print(message)
                    self.gui.status.update(message)
                    self.change_state(State.IDLE)
                del new_watching, selected_channel, watching_channel
            elif self._state is State.RESTART:
                raise ReloadRequest()
            elif self._state is State.EXIT:
                self.gui.tray.change_icon("pickaxe")
                self.gui.status.update(_("gui", "status", "exiting"))
                # we've been requested to exit the application
                break
            await self._state_change.wait()

    async def _watch_sleep(self, delay: float) -> None:
        # we use wait_for here to allow an asyncio.sleep-like that can be ended prematurely
        self._watching_restart.clear()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._watching_restart.wait(), timeout=max(0.0, delay))

    def _record_drop_progress(self, channel: Channel | None = None) -> None:
        """
        Reset the watchdog stall counter whenever real drop progress or an active
        drop session is confirmed via WebSocket or GQL.
        """
        self._no_progress_count = 0
        self._last_progress_time = time()
        target = channel or self.watching_channel.get_with_default(None)
        if target is not None:
            self.clear_stalled(target.id)

    def _get_watching_progress(self, channel: Channel) -> tuple[int, int] | None:
        """
        Compute aggregate (claimed_drops, real_current_minutes) across all drops in all
        earnable campaigns for the given channel (not just first_drop).
        """
        earnable_campaigns = [
            campaign for campaign in self.inventory if campaign.can_earn(channel)
        ]
        if not earnable_campaigns:
            active_campaign = self.get_active_campaign(channel)
            if active_campaign is not None:
                earnable_campaigns = [active_campaign]
        if not earnable_campaigns:
            return None
        total_claimed = sum(
            1 for campaign in earnable_campaigns for drop in campaign.drops if drop.is_claimed
        )
        total_real_minutes = sum(
            drop.real_current_minutes
            for campaign in earnable_campaigns
            for drop in campaign.drops
        )
        return (total_claimed, total_real_minutes)

    @task_wrapper(critical=True)
    async def _watch_loop(self) -> NoReturn:
        interval: float = WATCH_INTERVAL.total_seconds()
        # Watchdog state: track elapsed 60s windows with no drop progress across any
        # active/watching drop so a stalled channel cannot sit at 0% forever, while
        # avoiding false positives when progress occurs on non-first drops.
        last_progress: tuple[int, int] | None = None
        tracked_channel_id: int | None = None
        last_watchdog_check: float = 0.0
        while True:
            channel: Channel = await self.watching_channel.get()
            if not channel.online:
                # if the channel isn't online anymore, we stop watching it
                self.stop_watching()
                continue
            now_mono = time()
            if channel.id != tracked_channel_id:
                tracked_channel_id = channel.id
                self._no_progress_count = 0
                self._last_progress_time = now_mono
                last_watchdog_check = now_mono
                last_progress = self._get_watching_progress(channel)
                for campaign in self.inventory:
                    for drop in campaign.drops:
                        drop.extra_current_minutes = 0
            last_sent: float = now_mono
            try:
                # logger.log(CALL, f"Sending watch payload to: {channel.name}")
                succeeded: bool = await channel.send_watch()
                if not succeeded:
                    logger.log(CALL, f"Watch requested failed for channel: {channel.name}")
                else:
                    self._session_minutes_watched += 1
                    self.gui.progress.update_stats(
                        self._session_drops_claimed, self._session_minutes_watched
                    )
                    # Safeguard 2B: If watching a lower-priority game (priority > 0),
                    # periodically poll directories every 10 minutes to preempt immediately
                    # if a higher-priority game streamer has gone live.
                    if (
                        self._session_minutes_watched % 10 == 0
                        and self.get_priority(channel) > 0
                        and self._state is State.IDLE
                    ):
                        self.change_state(State.CHANNELS_CLEANUP)
                # wait ~15 seconds for a progress update
                await asyncio.sleep(max(0.0, 15 - min(time() - last_sent, 15)))
                if self.gui.progress.minute_almost_done():
                    # If the previous update was more than ~60s ago, and the progress tracker
                    # isn't counting down anymore, that means Twitch has temporarily
                    # stopped reporting drop's progress. To ensure the timer keeps at least somewhat
                    # accurate time, we can use GQL to query for the current drop,
                    # or even "pretend" mining as a last resort option.
                    handled: bool = False

                    # Solution 1: use GQL to query for the currently mined drop status
                    gql_failed: bool = False
                    try:
                        context = await self.gql_request(
                            GQL_QUERIES["CurrentDrop"].with_variables(
                                {"channelID": str(channel.id)}
                            )
                        )
                        drop_data: JsonType | None = (
                            ((context.get("data") or {}).get("currentUser") or {})
                            .get("dropCurrentSession")
                        )
                    except (GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError):
                        drop_data = None
                        gql_failed = True
                    if isinstance(drop_data, dict):
                        drop_id = drop_data.get("dropID")
                        gql_drop: TimedDrop | None = (
                            self._drops.get(drop_id) if isinstance(drop_id, str) else None
                        )
                        current_mins = drop_data.get("currentMinutesWatched")
                        session_channel = drop_data.get("channel")
                        session_channel_id = (
                            session_channel.get("id")
                            if isinstance(session_channel, dict)
                            else None
                        )
                        on_this_channel = session_channel_id == str(channel.id)
                        if gql_drop is not None and gql_drop.can_earn(channel):
                            prev_real = gql_drop.real_current_minutes
                            advanced = isinstance(current_mins, int) and current_mins > prev_real
                            # CurrentDrop can return a stale session from a different channel;
                            # only trust it if it's this channel or minutes are actually advancing.
                            if on_this_channel or advanced:
                                if isinstance(current_mins, int):
                                    gql_drop.update_minutes(current_mins)
                                if advanced:
                                    self._record_drop_progress(channel)
                                    drop_text: str = (
                                        f"{gql_drop.name} ({gql_drop.campaign.game}, "
                                        f"{gql_drop.current_minutes}/{gql_drop.required_minutes})"
                                    )
                                    logger.log(CALL, f"Drop progress from GQL: {drop_text}")
                                handled = True
                            else:
                                logger.log(
                                    CALL,
                                    f"Ignoring stale drop session from another channel "
                                    f"({session_channel_id}) for {channel.name}"
                                )
                        elif on_this_channel and isinstance(current_mins, int) and current_mins > 0:
                            # Drop session is present on this channel, but drop not in local inventory
                            handled = True

                    # Solution 2: only if the GQL query itself failed (network/API error),
                    # estimate progress. Never fabricate progress when GQL succeeded and
                    # reported nothing for this channel - the watchdog handles that case.
                    if not handled:
                        if gql_failed and (
                            active_campaign := self.get_active_campaign(channel)
                        ) is not None:
                            active_campaign.bump_minutes(channel)
                            # NOTE: This usually gets overwritten below
                            drop_text = f"Unknown drop ({active_campaign.game})"
                            if (active_drop := active_campaign.first_drop) is not None:
                                active_drop.display()
                                drop_text = (
                                    f"{active_drop.name} ({active_drop.campaign.game}, "
                                    f"{active_drop.current_minutes}/{active_drop.required_minutes})"
                                )
                            logger.log(CALL, f"Drop progress estimated (GQL failed): {drop_text}")
                            handled = True
                        else:
                            logger.log(CALL, f"No drop progress reported for {channel.name}")

                # Watchdog: detect a stalled channel where watch progress never advances
                # across any earnable drop in the active/earnable campaigns.
                progress = self._get_watching_progress(channel)
                now_check = time()
                if progress is None:
                    message = (
                        f"No earnable drops remaining on {channel.name} — switching channel..."
                    )
                    logger.info(message)
                    self.print(message)
                    self.mark_stalled(channel.id)
                    self._no_progress_count = 0
                    last_progress = None
                    self.stop_watching()
                    self.change_state(State.CHANNEL_SWITCH)
                    await self._watch_sleep(
                        interval - min(time() - last_sent, interval)
                    )
                    continue
                elif last_progress is None:
                    last_progress = progress
                    last_watchdog_check = now_check
                elif progress > last_progress:
                    last_progress = progress
                    self._record_drop_progress(channel)
                    last_watchdog_check = now_check
                elif now_check - self._last_progress_time < 60:
                    # A WebSocket drop-progress/claim or GQL session update recently confirmed progress
                    last_progress = progress
                    last_watchdog_check = now_check
                elif now_check - last_watchdog_check >= 60:
                    last_watchdog_check = now_check
                    self._no_progress_count += 1
                    if self._no_progress_count >= 7:
                        message = (
                            f"No drop progress detected on {channel.name} after "
                            f"{self._no_progress_count} minutes — switching channel..."
                        )
                        logger.warning(message)
                        self.print(message)
                        self.mark_stalled(channel.id)
                        self._no_progress_count = 0
                        last_progress = None
                        self.stop_watching()
                        self.change_state(State.CHANNEL_SWITCH)
                        jittered = interval + random.uniform(-1.8, 1.8)
                        await self._watch_sleep(
                            jittered - min(time() - last_sent, jittered)
                        )
                        continue
            except (ExitRequest, ReloadRequest, asyncio.CancelledError):
                raise
            except Exception as exc:
                logger.warning(f"Transient error in watch loop for {channel.name}: {exc}")
            jittered = interval + random.uniform(-1.8, 1.8)
            await self._watch_sleep(jittered - min(time() - last_sent, jittered))

    @task_wrapper(critical=True)
    async def _maintenance_task(self) -> None:
        now = datetime.now(timezone.utc)
        next_period = now + timedelta(hours=1)
        while True:
            # exit if there's no need to repeat the loop
            now = datetime.now(timezone.utc)
            if now >= next_period:
                break
            next_trigger = next_period
            while self._mnt_triggers and self._mnt_triggers[0] <= next_trigger:
                next_trigger = self._mnt_triggers.popleft()
            trigger_type: str = "Reload" if next_trigger == next_period else "Cleanup"
            logger.log(
                CALL,
                (
                    "Maintenance task waiting until: "
                    f"{next_trigger.astimezone().strftime('%X')} ({trigger_type})"
                )
            )
            await asyncio.sleep(max(0.0, (next_trigger - now).total_seconds()))
            # exit after waiting, before the actions
            now = datetime.now(timezone.utc)
            if now >= next_period:
                break
            if next_trigger != next_period:
                logger.log(CALL, "Maintenance task requests channels cleanup")
                self.change_state(State.CHANNELS_CLEANUP)
        # this triggers a restart of this task every (up to) 60 minutes
        logger.log(CALL, "Maintenance task requests a reload")
        self.change_state(State.INVENTORY_FETCH)

    def can_watch(self, channel: Channel) -> bool:
        """
        Determines if the given channel qualifies as a watching candidate.
        """
        # exit early if stream is offline
        if not channel.online:
            return False
        if self.is_game_excluded(channel.game):
            return False
        for campaign in self.inventory:
            if (
                not self.is_game_excluded(campaign.game)
                and campaign.game in self.wanted_games
                and campaign.can_earn(channel)  # let the campaign do the "special games" check
                and (
                    # limit watching to the games the user wants
                    channel.game is not None
                    and (channel.drops_enabled or (not campaign.allowed_channels and channel.game == campaign.game))
                    and channel.game in self.wanted_games
                    # let the campaign ignore all channel-related checks
                    or campaign.game.is_special()
                )
            ):
                return True
        return False

    def should_switch(self, channel: Channel) -> bool:
        """
        Determines if the given channel qualifies as a switch candidate.
        """
        if not self.can_watch(channel):
            return False
        if self.is_stalled(channel.id):
            # a channel with stalled watch progress is temporarily deprioritized
            return False
        watching_channel = self.watching_channel.get_with_default(None)
        if (
            watching_channel is None
            or not self.can_watch(watching_channel)
            or self.is_stalled(watching_channel.id)
        ):
            return True
        channel_order = self.get_priority(channel)
        watching_order = self.get_priority(watching_channel)
        channel_is_acl = channel.is_current_acl
        watching_is_acl = watching_channel.is_current_acl
        return (
            # this channel's game is higher order than the watching one's
            channel_order < watching_order
            or (
                channel_order == watching_order  # or the order is the same
                # and this channel is ACL-based for this game and the watching channel isn't
                and channel_is_acl > watching_is_acl
            )
        )

    def watch(self, channel: Channel, *, update_status: bool = True):
        self.gui.tray.change_icon("active")
        self.gui.channels.set_watching(channel)
        self.watching_channel.set(channel)
        if update_status:
            status_text = _("status", "watching").format(channel=channel.name)
            self.print(status_text)
            self.gui.status.update(status_text)
        self.restart_watching()

    def stop_watching(self):
        self.gui.clear_drop()
        self.watching_channel.clear()
        self.gui.channels.clear_watching()

    def restart_watching(self):
        self.gui.progress.stop_timer()
        self._watching_restart.set()

    @task_wrapper
    async def process_stream_state(self, channel_id: int, message: JsonType):
        msg_type = message["type"]
        channel = self.channels.get(channel_id)
        if channel is None:
            logger.error(f"Stream state change for a non-existing channel: {channel_id}")
            return
        if msg_type == "viewcount":
            if not channel.online:
                # if it's not online for some reason, set it so
                channel.check_online()
            else:
                viewers = message["viewers"]
                channel.viewers = viewers
                channel.display()
                # logger.debug(f"{channel.name} viewers: {viewers}")
        elif msg_type == "stream-down":
            channel.set_offline()
        elif msg_type == "stream-up":
            channel.check_online()
        elif msg_type == "commercial":
            # skip these
            pass
        else:
            logger.warning(f"Unknown stream state: {msg_type}")

    @task_wrapper
    async def process_stream_update(self, channel_id: int, message: JsonType):
        # message = {
        #     "channel_id": "12345678",
        #     "type": "broadcast_settings_update",
        #     "channel": "channel._login",
        #     "old_status": "Old title",
        #     "status": "New title",
        #     "old_game": "Old game name",
        #     "game": "New game name",
        #     "old_game_id": 123456,
        #     "game_id": 123456
        # }
        channel = self.channels.get(channel_id)
        if channel is None:
            logger.error(f"Broadcast settings update for a non-existing channel: {channel_id}")
            return
        if message["old_game"] != message["game"]:
            game_change = f", game changed: {message['old_game']} -> {message['game']}"
        else:
            game_change = ''
        logger.log(CALL, f"Channel update from websocket: {channel.name}{game_change}")
        # Safeguard 2C: If the currently watched channel changes game category (e.g. switches
        # to Just Chatting or raids out), update stream info after a short 3s settle instead
        # of waiting the full 120s ONLINE_DELAY so we can switch immediately.
        watching_channel = self.watching_channel.get_with_default(None)
        if watching_channel is not None and watching_channel == channel and message["old_game"] != message["game"]:
            await asyncio.sleep(3)
            await channel.update_stream()
            return
        # There's no information about channel tags here, but this event is triggered
        # when the tags change. We can use this to just update the stream data after the change.
        # Use 'check_online' to introduce a delay, allowing for multiple title and tags
        # changes before we update. This eventually calls 'on_channel_update' below.
        channel.check_online()

    def on_channel_update(
        self, channel: Channel, stream_before: Stream | None, stream_after: Stream | None
    ):
        """
        Called by a Channel when it's status is updated (ONLINE, OFFLINE, title/tags change).

        NOTE: 'stream_before' gets dealocated once this function finishes.
        """
        if stream_before is None:
            if stream_after is not None:
                # Channel going ONLINE
                if self.should_switch(channel):
                    # we can watch the channel, and we should
                    self.print(_("status", "goes_online").format(channel=channel.name))
                    self.watch(channel)
                else:
                    logger.info(f"{channel.name} goes ONLINE")
            else:
                # Channel was OFFLINE and stays that way
                logger.log(CALL, f"{channel.name} stays OFFLINE")
        else:
            watching_channel = self.watching_channel.get_with_default(None)
            # check if the watching channel was the one updated
            if watching_channel is not None and watching_channel == channel:
                # NOTE: In these cases, channel was the watching channel
                if not self.can_watch(channel):
                    # we can't watch it anymore
                    if stream_after is None:
                        # Channel going OFFLINE
                        self.print(_("status", "goes_offline").format(channel=channel.name))
                    else:
                        # Channel stays ONLINE, but we can't watch it anymore
                        if stream_before.game != stream_after.game:
                            self.print(
                                f"{channel.name} changed category ({stream_before.game} -> "
                                f"{stream_after.game}), switching..."
                            )
                        logger.info(
                            f"{channel.name} status has been updated, switching... "
                            f"(🎁: {stream_before.drops_enabled and '✔' or '❌'} -> "
                            f"{stream_after.drops_enabled and '✔' or '❌'})"
                        )
                    self.change_state(State.CHANNEL_SWITCH)
                elif (
                    stream_after is not None
                    and stream_before.game != stream_after.game
                    and any(self.should_switch(ch) for ch in self.channels.values())
                ):
                    # Channel switched to a lower-priority game while a higher-priority channel is online
                    self.print(
                        f"{channel.name} changed category ({stream_before.game} -> "
                        f"{stream_after.game}), switching to higher-priority stream..."
                    )
                    self.change_state(State.CHANNEL_SWITCH)
                else:
                    # Channel stays ONLINE, and we can still watch it - no change
                    pass
            # NOTE: In these cases, it wasn't the watching channel
            elif stream_after is None:
                logger.info(f"{channel.name} goes OFFLINE")
            else:
                # Channel stays ONLINE, but has been updated
                logger.info(
                    f"{channel.name} status has been updated "
                    f"(🎁: {stream_before.drops_enabled and '✔' or '❌'} -> "
                    f"{stream_after.drops_enabled and '✔' or '❌'})"
                )
                if self.should_switch(channel):
                    # ... and we should watch it
                    self.watch(channel)
        channel.display()

    @task_wrapper
    async def process_drops(self, user_id: int, message: JsonType):
        # Message examples:
        # {"type": "drop-progress", data: {"current_progress_min": 3, "required_progress_min": 10}}
        # {"type": "drop-claim", data: {"drop_instance_id": ...}}
        msg_type: str = message["type"]
        if msg_type not in ("drop-progress", "drop-claim"):
            return
        drop_id: str = message["data"]["drop_id"]
        drop: TimedDrop | None = self._drops.get(drop_id)
        watching_channel: Channel | None = self.watching_channel.get_with_default(None)
        if msg_type == "drop-claim":
            if drop is None:
                logger.error(
                    f"Received a drop claim ID for a non-existing drop: {drop_id}\n"
                    f"Drop claim ID: {message['data']['drop_instance_id']}"
                )
                return
            self._record_drop_progress(watching_channel)
            drop.update_claim(message["data"]["drop_instance_id"])
            campaign = drop.campaign
            await drop.claim()
            drop.display()
            # About 4-20s after claiming the drop, next drop can be started
            # by re-sending the watch payload. We can test for it by fetching the current drop
            # via GQL, and then comparing drop IDs.
            await asyncio.sleep(4)
            if watching_channel is not None:
                for attempt in range(8):
                    try:
                        context = await self.gql_request(
                            GQL_QUERIES["CurrentDrop"].with_variables(
                                {"channelID": str(watching_channel.id)}
                            )
                        )
                        drop_data: JsonType | None = (
                            context.get("data", {})
                            .get("currentUser", {})
                            .get("dropCurrentSession")
                        )
                    except (GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError):
                        break
                    if drop_data is None or drop_data.get("dropID") != drop.id:
                        break
                    await asyncio.sleep(2)
            if campaign.can_earn(watching_channel):
                self.restart_watching()
            else:
                self.change_state(State.INVENTORY_FETCH)
            return
        assert msg_type == "drop-progress"
        self._record_drop_progress(watching_channel)
        if drop is not None:
            drop_text = (
                f"{drop.name} ({drop.campaign.game}, "
                f"{message['data']['current_progress_min']}/"
                f"{message['data']['required_progress_min']})"
            )
        else:
            drop_text = "<Unknown>"
        logger.log(CALL, f"Drop update from websocket: {drop_text}")
        if drop is not None and drop.can_earn(watching_channel):
            # the received payload is for the drop we expected
            drop.update_minutes(message["data"]["current_progress_min"])

    @task_wrapper
    async def process_notifications(self, user_id: int, message: JsonType):
        if message["type"] == "create-notification":
            data: JsonType = message["data"]["notification"]
            if data["type"] in (
                "user_drop_reward_reminder_notification",  # drop confirmation
                "quests_viewer_reward_campaign_earned_emote",  # emote confirmation
                # badge confirmation?
            ):
                self.change_state(State.INVENTORY_FETCH)
                with suppress(GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError):
                    await self.gql_request(
                        GQL_QUERIES["NotificationsDelete"].with_variables(
                            {"input": {"id": data["id"]}}
                        )
                    )

    async def get_auth(self) -> _AuthState:
        await self._auth_state.validate()
        return self._auth_state

    @asynccontextmanager
    async def request(
        self, method: str, url: URL | str, *, invalidate_after: datetime | None = None, **kwargs
    ) -> abc.AsyncIterator[aiohttp.ClientResponse]:
        session = await self.get_session()
        method = method.upper()
        if self.settings.proxy and "proxy" not in kwargs:
            kwargs["proxy"] = self.settings.proxy
        logger.debug(f"Request: ({method=}, {url=}, {kwargs=})")
        session_timeout = timedelta(seconds=session.timeout.total or 0)
        backoff = ExponentialBackoff(maximum=3*60)
        for delay in backoff:
            if self.gui.close_requested:
                raise ExitRequest()
            elif (
                invalidate_after is not None
                # account for the expiration landing during the request
                and datetime.now(timezone.utc) >= (invalidate_after - session_timeout)
            ):
                raise RequestInvalid()
            response: aiohttp.ClientResponse | None = None
            try:
                response = await self.gui.coro_unless_closed(
                    session.request(method, url, **kwargs)
                )
                assert response is not None
                logger.debug(f"Response: {response.status}: {response}")
                if response.status < 500:
                    # pre-read the response to avoid getting errors outside of the context manager
                    raw_response = await response.read()  # noqa
                    yield response
                    return
                self.print(_("error", "site_down").format(seconds=round(delay)))
            except aiohttp.ClientConnectorCertificateError:
                # for a case where SSL verification fails
                raise
            except (
                aiohttp.ClientConnectionError, asyncio.TimeoutError, aiohttp.ClientPayloadError
            ):
                # connection problems, retry
                if backoff.steps > 1:
                    # just so that quick retries that sometimes happen, aren't shown
                    self.print(
                        _("error", "no_connection").format(seconds=round(delay), url=str(url))
                    )
            finally:
                if response is not None:
                    response.release()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.gui.wait_until_closed(), timeout=delay)

    @overload
    async def gql_request(self, ops: GQLOperation) -> JsonType:
        ...

    @overload
    async def gql_request(self, ops: list[GQLOperation]) -> list[JsonType]:
        ...

    async def gql_request(
        self, ops: GQLOperation | list[GQLOperation]
    ) -> JsonType | list[JsonType]:
        gql_logger.debug(f"GQL Request: {ops}")
        backoff = ExponentialBackoff(maximum=60)
        # Use a flag to retry the request a single time, if a specific set of errors is encountered
        single_retry: bool = True
        for delay in backoff:
            async with self._qgl_limiter:
                auth_state = await self.get_auth()
                async with self.request(
                    "POST",
                    "https://gql.twitch.tv/gql",
                    json=ops,
                    headers=auth_state.headers(user_agent=self._client_type.USER_AGENT, gql=True),
                ) as response:
                    response_json: JsonType | list[JsonType] = await response.json()
            gql_logger.debug(f"GQL Response: {response_json}")
            orig_response = response_json
            if isinstance(response_json, list):
                response_list = response_json
            else:
                response_list = [response_json]
            force_retry: bool = False
            for response_index, response_json in enumerate(response_list):
                if not isinstance(response_json, dict):
                    raise GQLException(f"Unexpected GQL response: {response_json!r}")

                # Twitch error responses do not consistently include
                # extensions.operationName. Fall back to the submitted operation so
                # logging an error never becomes a second, fatal KeyError.
                extensions = response_json.get("extensions")
                operation_name: str | None = (
                    cast(str | None, extensions.get("operationName"))
                    if isinstance(extensions, dict)
                    else None
                )
                if operation_name is None:
                    submitted_op: GQLOperation | None
                    if isinstance(ops, list):
                        submitted_op = ops[response_index] if response_index < len(ops) else None
                    else:
                        submitted_op = ops
                    if isinstance(submitted_op, dict):
                        operation_name = cast(str | None, submitted_op.get("operationName"))
                operation_name = operation_name or "<unknown operation>"

                # GQL error handling
                if "errors" in response_json:
                    handled_error = False
                    for error_dict in response_json["errors"]:
                        if not isinstance(error_dict, dict):
                            continue
                        message = error_dict.get("message")
                        if not isinstance(message, str):
                            continue

                        if message == "PersistedQueryNotFound" and single_retry:
                            logger.error(f"Retrying {message} for {operation_name}")
                            single_retry = False
                            if delay < 5:
                                delay = 5
                            force_retry = True
                            handled_error = True
                            break

                        if message == "server error":
                            # Some server errors include a valid GraphQL path so the
                            # failed field can be treated as null. If Twitch omits or
                            # changes that path, retry instead of crashing on path[-1].
                            data_obj = response_json.get("data")
                            path = error_dict.get("path")
                            if isinstance(data_obj, dict) and isinstance(path, list) and path:
                                target: Any = data_obj
                                try:
                                    for key in path[:-1]:
                                        target = target[key]
                                    target[path[-1]] = None
                                except (KeyError, IndexError, TypeError):
                                    force_retry = True
                                handled_error = True
                                break
                            force_retry = True
                            handled_error = True
                            break

                        if message in (
                            "service error",
                            "service timeout",
                            "request cancelled",
                            "service unavailable",
                            "context deadline exceeded",
                        ):
                            logger.warning(f"Retrying {message} for {operation_name}")
                            force_retry = True
                            handled_error = True
                            break

                    if not handled_error:
                        raise GQLException(response_json["errors"])
                # Other error handling
                elif "error" in response_json:
                    raise GQLException(
                        f"{response_json.get('error', 'GQL error')}: "
                        f"{response_json.get('message', 'No message')}"
                    )
                if force_retry:
                    break
            else:
                return orig_response
            await asyncio.sleep(delay)
        raise RuntimeError("Retry loop was broken")

    def _merge_data(self, primary_data: JsonType, secondary_data: JsonType) -> JsonType:
        merged = {}
        for key in set(chain(primary_data.keys(), secondary_data.keys())):
            in_primary = key in primary_data
            if in_primary and key in secondary_data:
                vp = primary_data[key]
                vs = secondary_data[key]
                if vp is None:
                    merged[key] = vs
                elif vs is None:
                    merged[key] = vp
                elif not isinstance(vp, type(vs)) or not isinstance(vs, type(vp)):
                    raise MinerException("Inconsistent merge data")
                elif isinstance(vp, dict):  # both are dicts
                    merged[key] = self._merge_data(vp, vs)
                else:
                    # use primary value
                    merged[key] = vp
            elif in_primary:
                merged[key] = primary_data[key]
            else:  # in campaigns only
                merged[key] = secondary_data[key]
        return merged

    async def fetch_campaigns(
        self, campaigns_chunk: list[tuple[str, JsonType]]
    ) -> dict[str, JsonType]:
        campaign_ids: dict[str, JsonType] = dict(campaigns_chunk)
        auth_state = await self.get_auth()
        try:
            response_list: list[JsonType] = await self.gql_request(
                [
                    GQL_QUERIES["CampaignDetails"].with_variables(
                        {"channelLogin": str(auth_state.user_id), "dropID": cid}
                    )
                    for cid in campaign_ids
                ]
            )
        except (GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning(f"Failed to fetch campaign details chunk: {exc}")
            return campaign_ids
        fetched_data: dict[str, JsonType] = {}
        for response_json in response_list:
            if not isinstance(response_json, dict):
                continue
            data_obj = response_json.get("data")
            if not isinstance(data_obj, dict):
                continue
            user_obj = data_obj.get("user")
            if not isinstance(user_obj, dict):
                continue
            campaign_data = user_obj.get("dropCampaign")
            if isinstance(campaign_data, dict) and isinstance(campaign_data.get("id"), str):
                fetched_data[campaign_data["id"]] = campaign_data
        return self._merge_data(campaign_ids, fetched_data)

    async def fetch_campaign_catalog(self) -> dict[str, JsonType]:
        """
        Fetch full campaign metadata from the public Twitch Drops catalog.

        Twitch's SMARTBOX client can still use the device OAuth flow, but Twitch
        intentionally returns an empty/incomplete ViewerDropsDashboard response for it.
        The catalog is used only for public campaign metadata; authentication, inventory
        progress, websocket updates, watch events and claiming remain direct Twitch calls.
        """
        catalog_url = "https://twitch-drops-api.sunkwi.com/v2/drops"
        request_kwargs: JsonType = {"headers": {"Accept": "application/json"}}
        if self.settings.proxy:
            request_kwargs["proxy"] = self.settings.proxy

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(
                timeout=timeout,
                cookie_jar=aiohttp.DummyCookieJar(),
                headers={"User-Agent": "TwitchDropsMiner campaign fallback"},
            ) as session:
                async with session.get(catalog_url, **request_kwargs) as response:
                    if response.status != 200:
                        raise RequestException(
                            f"Campaign catalog returned HTTP {response.status}"
                        )
                    payload: JsonType = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RequestException) as exc:
            logger.warning(f"Campaign catalog fallback failed: {exc}")
            return {}

        groups = payload.get("data")
        if not isinstance(groups, list):
            logger.warning("Campaign catalog fallback returned an invalid payload")
            return {}

        # Reject materially stale snapshots instead of presenting campaigns that
        # may already have ended. The service advertises a 60-second refresh
        # interval, but allow a generous grace period for transient delays.
        last_updated_raw = payload.get("lastUpdatedAt")
        refresh_interval = payload.get("refreshIntervalSeconds", 60)
        try:
            refresh_seconds = max(1, int(refresh_interval))
            last_updated = timestamp(cast(str, last_updated_raw))
        except (TypeError, ValueError):
            logger.warning("Campaign catalog fallback returned invalid freshness metadata")
            return {}
        now = datetime.now(timezone.utc)
        max_age = timedelta(seconds=max(300, refresh_seconds * 5))
        if last_updated > now + timedelta(minutes=2) or now - last_updated > max_age:
            logger.warning(
                "Campaign catalog fallback is stale; refusing to use outdated campaign data"
            )
            return {}

        applicable_statuses = ("ACTIVE", "UPCOMING")
        campaigns: dict[str, JsonType] = {}
        for group in groups:
            if not isinstance(group, dict):
                continue
            box_art_url = group.get("gameBoxArtURL", "")
            rewards = group.get("rewards") or []
            if not isinstance(rewards, list):
                continue
            for raw_campaign in rewards:
                if not isinstance(raw_campaign, dict):
                    continue
                campaign_id = raw_campaign.get("id")
                if (
                    not isinstance(campaign_id, str)
                    or raw_campaign.get("status") not in applicable_statuses
                ):
                    continue
                try:
                    campaign_start = timestamp(cast(str, raw_campaign["startAt"]))
                    campaign_end = timestamp(cast(str, raw_campaign["endAt"]))
                except (KeyError, TypeError, ValueError):
                    continue
                # Do not trust a cached ACTIVE/UPCOMING status after the real end
                # timestamp. This prevents ended campaigns from resurfacing if the
                # public catalog is briefly behind Twitch.
                if campaign_end <= now:
                    continue

                campaign: JsonType = deepcopy(raw_campaign)
                game = campaign.get("game")
                if not isinstance(game, dict):
                    continue
                game.setdefault("boxArtURL", box_art_url)

                # The public catalog cannot know account-specific linkage state.
                # Default catalog-only campaigns to False until verified against the
                # user's authenticated Inventory (ongoing campaigns and gameEventDrops)
                # during fetch_inventory().
                if not isinstance(campaign.get("self"), dict):
                    campaign["self"] = {"isAccountConnected": False}
                else:
                    campaign["self"].setdefault("isAccountConnected", False)

                allowed = campaign.get("allow")
                if not isinstance(allowed, dict):
                    allowed = {"isEnabled": False, "channels": None}
                    campaign["allow"] = allowed
                else:
                    allowed.setdefault("channels", None)

                if not isinstance(campaign.get("timeBasedDrops"), list):
                    campaign["timeBasedDrops"] = []
                campaign.setdefault("accountLinkURL", "")
                campaigns[campaign_id] = campaign

        logger.warning(
            "Twitch did not expose the full campaign list to the SMARTBOX client; "
            f"using public campaign metadata fallback ({len(campaigns)} campaigns)."
        )
        return campaigns

    @staticmethod
    def _normalize_link_info(url_str: str) -> tuple[str, str]:
        url_str = (url_str or "").strip()
        if not url_str:
            return ("", "")
        try:
            parsed = URL(url_str)
        except ValueError:
            return ("", "")
        host = (parsed.host or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return ("", "")
        path = parsed.path.rstrip("/").lower()
        frag = f"#{parsed.fragment.lower()}" if parsed.fragment else ""
        if host in ("twitch.tv", "m.twitch.tv", "help.twitch.tv", "id.twitch.tv"):
            if "riot-connection" in frag:
                return (f"{host}{path}{frag}", "riot-connection")
            return ("", "")
        return (f"{host}{path}{frag}", host)

    async def fetch_inventory(self) -> None:
        status_update = self.gui.status.update
        status_update(_("gui", "status", "fetching_inventory"))
        # fetch in-progress campaigns (inventory)
        response = await self.gql_request(GQL_QUERIES["Inventory"])
        current_user: JsonType = (response.get("data") or {}).get("currentUser") or {}
        inventory: JsonType = current_user.get("inventory") or {}
        ongoing_campaigns: list[JsonType] = inventory.get("dropCampaignsInProgress") or []
        game_event_drops: list[JsonType] = inventory.get("gameEventDrops") or []
        # this contains claimed benefit edge IDs, not drop IDs
        claimed_benefits: dict[str, datetime] = {
            b["id"]: timestamp(b["lastAwardedAt"])
            for b in game_event_drops
            if isinstance(b, dict) and "id" in b and "lastAwardedAt" in b
        }
        inventory_data: dict[str, JsonType] = {
            c["id"]: c for c in ongoing_campaigns if isinstance(c, dict) and "id" in c
        }
        # fetch general available campaigns data (campaigns)
        available_list: list[JsonType] = []
        try:
            response = await self.gql_request(GQL_QUERIES["Campaigns"])
            available_list = (
                ((response.get("data") or {}).get("currentUser") or {}).get("dropCampaigns") or []
            )
        except GQLException as exc:
            if self._client_type is not ClientType.SMARTBOX:
                raise
            logger.warning(f"ViewerDropsDashboard query failed on SMARTBOX client: {exc}")
        applicable_statuses = ("ACTIVE", "UPCOMING")
        available_campaigns: dict[str, JsonType] = {
            c["id"]: c
            for c in available_list
            if isinstance(c, dict) and c.get("status") in applicable_statuses
        }
        status_update(_("gui", "status", "fetching_campaigns"))
        if self._client_type is ClientType.SMARTBOX:
            # SMARTBOX can authenticate, but Twitch does not expose the complete
            # campaign dashboard to this client. Use public metadata as the
            # discovery layer and keep account-specific inventory data authoritative.
            catalog_campaigns = await self.fetch_campaign_catalog()
            # Resolve account linkage for catalog campaigns using authoritative
            # signals from Twitch's Inventory response (dropCampaignsInProgress
            # and gameEventDrops.requiredAccountLink / isConnected).
            connected_game_ids: set[str] = set()
            unlinked_game_ids: set[str] = set()
            for ongoing in inventory_data.values():
                ongoing_game = ongoing.get("game")
                ongoing_self = ongoing.get("self")
                if (
                    isinstance(ongoing_game, dict)
                    and isinstance(ongoing_self, dict)
                    and ongoing_game.get("id") is not None
                ):
                    gid = str(ongoing_game["id"])
                    is_conn = ongoing_self.get("isAccountConnected")
                    if is_conn is True:
                        connected_game_ids.add(gid)
                    elif is_conn is False:
                        unlinked_game_ids.add(gid)

            connected_links: set[str] = set()
            connected_domains: set[str] = set()
            unlinked_links: set[str] = set()
            for benefit_entry in game_event_drops:
                if not isinstance(benefit_entry, dict):
                    continue
                req_link = str(benefit_entry.get("requiredAccountLink") or "")
                full_key, domain_key = self._normalize_link_info(req_link)
                if not full_key:
                    continue
                if benefit_entry.get("isConnected") is True:
                    connected_links.add(full_key)
                    if domain_key:
                        connected_domains.add(domain_key)
                elif benefit_entry.get("isConnected") is False:
                    unlinked_links.add(full_key)

            # First pass: propagate publisher link connection to game IDs in the catalog
            # (unless explicitly known unlinked in ongoing campaigns).
            for catalog_campaign in catalog_campaigns.values():
                cat_game = catalog_campaign.get("game")
                gid = str(cat_game.get("id")) if isinstance(cat_game, dict) and cat_game.get("id") is not None else ""
                if not gid or gid in unlinked_game_ids:
                    continue
                link_url = str(catalog_campaign.get("accountLinkURL") or "")
                full_key, domain_key = self._normalize_link_info(link_url)
                if full_key and full_key not in unlinked_links and (
                    full_key in connected_links or (domain_key and domain_key in connected_domains)
                ):
                    connected_game_ids.add(gid)

            # Second pass: assign accurate isAccountConnected to each catalog campaign.
            for catalog_campaign in catalog_campaigns.values():
                cat_game = catalog_campaign.get("game")
                gid = str(cat_game.get("id")) if isinstance(cat_game, dict) and cat_game.get("id") is not None else ""
                link_url = str(catalog_campaign.get("accountLinkURL") or "")
                full_key, domain_key = self._normalize_link_info(link_url)
                if gid and gid in unlinked_game_ids:
                    is_linked = False
                elif gid and gid in connected_game_ids:
                    is_linked = True
                elif full_key and full_key not in unlinked_links and (
                    full_key in connected_links or (domain_key and domain_key in connected_domains)
                ):
                    is_linked = True
                else:
                    is_linked = False
                cat_self = catalog_campaign.get("self")
                if not isinstance(cat_self, dict):
                    cat_self = {}
                    catalog_campaign["self"] = cat_self
                cat_self["isAccountConnected"] = is_linked

            inventory_data = self._merge_data(inventory_data, catalog_campaigns)
        else:
            # Normal clients can still resolve campaign details directly from Twitch.
            fetch_campaigns_tasks: list[asyncio.Task[Any]] = [
                asyncio.create_task(self.fetch_campaigns(campaigns_chunk))
                for campaigns_chunk in chunk(available_campaigns.items(), 20)
            ]
            try:
                for coro in asyncio.as_completed(fetch_campaigns_tasks):
                    chunk_campaigns_data = await coro
                    # merge the inventory and campaigns datas together
                    inventory_data = self._merge_data(inventory_data, chunk_campaigns_data)
            except (Exception, asyncio.CancelledError):
                # asyncio.as_completed doesn't cancel tasks on errors
                for task in fetch_campaigns_tasks:
                    task.cancel()
                await asyncio.gather(*fetch_campaigns_tasks, return_exceptions=True)
                raise
        # filter out invalid campaigns
        for campaign_id in list(inventory_data.keys()):
            if inventory_data[campaign_id].get("game") is None:
                del inventory_data[campaign_id]

        if self.settings.dump:
            # dump the campaigns data to the dump file
            with open(DUMP_PATH, 'a', encoding="utf8") as file:
                # we need to pre-process the inventory dump a little
                dump_data: JsonType = deepcopy(inventory_data)
                for campaign_data in dump_data.values():
                    # replace ACL lists with a simple text description
                    if (
                        campaign_data.get("allow")
                        and campaign_data["allow"].get("isEnabled", True)
                        and campaign_data["allow"].get("channels")
                    ):
                        # simply count the channels included in the ACL
                        campaign_data["allow"]["channels"] = (
                            f"{len(campaign_data['allow']['channels'])} channels"
                        )
                    # replace drop instance IDs, so they don't include user IDs
                    for drop_data in (campaign_data.get("timeBasedDrops") or []):
                        if isinstance(drop_data.get("self"), dict) and drop_data["self"].get("dropInstanceID"):
                            drop_data["self"]["dropInstanceID"] = "..."
                json.dump(dump_data, file, indent=4, sort_keys=True)
                file.write("\n\n")  # add 2x new line spacer
                json.dump(game_event_drops, file, indent=4, sort_keys=True, default=str)

        # use the merged data to create campaign objects
        campaigns: list[DropsCampaign] = [
            DropsCampaign(self, campaign_data, claimed_benefits)
            for campaign_data in inventory_data.values()
        ]
        campaigns.sort(key=lambda c: c.active, reverse=True)
        campaigns.sort(key=lambda c: c.upcoming and c.starts_at or c.ends_at)
        campaigns.sort(key=lambda c: c.eligible, reverse=True)

        self._drops.clear()
        self._campaigns.clear()
        self.gui.inv.clear()
        self.inventory.clear()
        self._mnt_triggers.clear()
        switch_triggers: set[datetime] = set()
        next_hour = datetime.now(timezone.utc) + timedelta(hours=1)
        # add the campaigns to the internal inventory
        for campaign in campaigns:
            self._drops.update({drop.id: drop for drop in campaign.drops})
            if campaign.can_earn_within(next_hour):
                switch_triggers.update(campaign.time_triggers)
            self.inventory.append(campaign)
            self._campaigns[campaign.id] = campaign
        # Register campaigns in the virtualized GUI. add_campaign() is now
        # model-only, so creating one asyncio task per campaign would just add
        # scheduler overhead. Yield periodically to keep Tk responsive.
        status_update(
            _("gui", "status", "adding_campaigns").format(counter=f"(0/{len(campaigns)})")
        )
        for i, campaign in enumerate(campaigns, start=1):
            self.gui.inv.add_campaign(campaign)
            if i == len(campaigns) or i % 25 == 0:
                status_update(
                    _("gui", "status", "adding_campaigns").format(
                        counter=f"({i}/{len(campaigns)})"
                    )
                )
                await asyncio.sleep(0)
            if self.gui.close_requested:
                raise ExitRequest()
        self._mnt_triggers.extend(sorted(switch_triggers))
        # trim out all triggers that we're already past
        now = datetime.now(timezone.utc)
        while self._mnt_triggers and self._mnt_triggers[0] <= now:
            self._mnt_triggers.popleft()
        # NOTE: maintenance task is restarted at the end of each inventory fetch
        if self._mnt_task is not None and not self._mnt_task.done():
            self._mnt_task.cancel()
        self._mnt_task = asyncio.create_task(self._maintenance_task())

    def get_active_campaign(self, channel: Channel | None = None) -> DropsCampaign | None:
        if not self.wanted_games:
            return None
        watching_channel = self.watching_channel.get_with_default(channel)
        if watching_channel is None:
            # if we aren't watching anything, we can't earn any drops
            return None
        campaigns: list[DropsCampaign] = []
        for campaign in self.inventory:
            if campaign.can_earn(watching_channel):
                campaigns.append(campaign)
        if campaigns:
            campaigns.sort(key=lambda c: c.remaining_minutes)
            return campaigns[0]
        return None

    def _game_directory_op(
        self, game: Game, *, limit: int = 20, drops_enabled: bool = True
    ) -> GQLOperation:
        filters: list[str] = []
        if drops_enabled:
            filters.append("DROPS_ENABLED")
        return GQL_QUERIES["GameDirectory"].with_variables({
            "limit": limit,
            "slug": game.slug,
            "options": {
                "includeRestricted": ["SUB_ONLY_LIVE"],
                "systemFilters": filters,
            },
        })

    def _channels_from_game_directory(
        self, response: JsonType, *, drops_enabled: bool
    ) -> list[Channel]:
        if not isinstance(response, dict):
            return []
        data = response.get("data")
        if not isinstance(data, dict):
            return []
        game_data = data.get("game")
        if not isinstance(game_data, dict):
            return []
        streams = game_data.get("streams")
        if not isinstance(streams, dict):
            return []
        edges = streams.get("edges")
        if not isinstance(edges, list):
            return []
        channels: list[Channel] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if not isinstance(node, dict) or node.get("broadcaster") is None:
                continue
            with suppress(KeyError, TypeError, ValueError):
                channels.append(
                    Channel.from_directory(self, node, drops_enabled=drops_enabled)
                )
        return channels

    async def get_live_streams(
        self, game: Game, *, limit: int = 20, drops_enabled: bool = True
    ) -> list[Channel]:
        try:
            response = await self.gql_request(
                self._game_directory_op(
                    game,
                    limit=limit,
                    drops_enabled=drops_enabled,
                )
            )
        except GQLException as exc:
            raise MinerException(f"Game: {game.slug}") from exc
        return self._channels_from_game_directory(
            response,
            drops_enabled=drops_enabled,
        )

    async def get_live_streams_bulk(
        self,
        games: abc.Iterable[Game],
        *,
        limit: int = 20,
        drops_enabled: bool = True,
    ) -> list[Channel]:
        """
        Fetch live channels for multiple games using batched GQL operations.

        Twitch accepts lists of persisted GQL operations. Grouping up to 20
        GameDirectory queries per request removes the old one-request-per-game
        latency while preserving fresh discovery on every channel refresh.
        """
        game_list = list(games)
        if not game_list:
            return []

        operations: list[GQLOperation] = [
            self._game_directory_op(
                game,
                limit=limit,
                drops_enabled=drops_enabled,
            )
            for game in game_list
        ]
        tasks: list[asyncio.Task[list[JsonType]]] = [
            asyncio.create_task(self.gql_request(operation_chunk))
            for operation_chunk in chunk(operations, 20)
        ]

        channels: list[Channel] = []
        try:
            for coro in asyncio.as_completed(tasks):
                try:
                    response_list: list[JsonType] = await coro
                except (GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    game_names = ", ".join(game.slug for game in game_list)
                    logger.warning(f"Bulk stream discovery error for games ({game_names}): {exc}")
                    continue
                for response in response_list:
                    channels.extend(
                        self._channels_from_game_directory(
                            response,
                            drops_enabled=drops_enabled,
                        )
                    )
        except (Exception, asyncio.CancelledError):
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return channels

    async def bulk_check_online(
        self,
        channels: abc.Iterable[Channel],
        *,
        check_available_drops: bool | None = None,
    ):
        """
        Utilize batch GQL requests to check ONLINE status for a lot of channels at once.

        AvailableDrops verification can be deferred until after channel ranking/trimming
        so discarded ACL candidates do not consume extra GQL requests.
        """
        channel_list = list(channels)
        acl_streams_map: dict[int, JsonType] = {}
        stream_gql_ops: list[GQLOperation] = [channel.stream_gql for channel in channel_list]
        if not stream_gql_ops:
            # shortcut for nothing to process
            # NOTE: Have to do this here, becase "channels" can be any iterable
            return
        stream_gql_tasks: list[asyncio.Task[list[JsonType]]] = [
            asyncio.create_task(self.gql_request(stream_gql_chunk))
            for stream_gql_chunk in chunk(stream_gql_ops, 20)
        ]
        try:
            for coro in asyncio.as_completed(stream_gql_tasks):
                try:
                    response_list: list[JsonType] = await coro
                except (GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning(f"Bulk online check batch failed: {exc}")
                    continue
                for response_json in response_list:
                    if not isinstance(response_json, dict):
                        continue
                    data = response_json.get("data")
                    if not isinstance(data, dict):
                        continue
                    channel_data: JsonType | None = data.get("user")
                    if isinstance(channel_data, dict) and channel_data.get("id") is not None:
                        acl_streams_map[int(channel_data["id"])] = channel_data
        except (Exception, asyncio.CancelledError):
            # asyncio.as_completed doesn't cancel tasks on errors
            for task in stream_gql_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*stream_gql_tasks, return_exceptions=True)
            raise
        if check_available_drops is None:
            check_available_drops = self.settings.available_drops_check

        # for all channels with an active stream, check the available drops as well
        acl_available_drops_map: dict[int, list[JsonType]] = {}
        if check_available_drops:
            available_gql_ops: list[GQLOperation] = [
                GQL_QUERIES["AvailableDrops"].with_variables({"channelID": str(channel_id)})
                for channel_id, channel_data in acl_streams_map.items()
                if channel_data.get("stream") is not None  # only do this for ONLINE channels
            ]
            available_gql_tasks: list[asyncio.Task[list[JsonType]]] = [
                asyncio.create_task(self.gql_request(available_gql_chunk))
                for available_gql_chunk in chunk(available_gql_ops, 20)
            ]
            try:
                for coro in asyncio.as_completed(available_gql_tasks):
                    try:
                        response_list = await coro
                    except (GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        logger.warning(f"Bulk available drops batch failed: {exc}")
                        continue
                    for response_json in response_list:
                        if not isinstance(response_json, dict):
                            continue
                        data = response_json.get("data")
                        if not isinstance(data, dict):
                            continue
                        available_info: JsonType | None = data.get("channel")
                        if isinstance(available_info, dict) and available_info.get("id") is not None:
                            acl_available_drops_map[int(available_info["id"])] = (
                                available_info.get("viewerDropCampaigns") or []
                            )
            except (Exception, asyncio.CancelledError):
                # asyncio.as_completed doesn't cancel tasks on errors
                for task in available_gql_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*available_gql_tasks, return_exceptions=True)
                raise
        for channel in channel_list:
            channel_id = channel.id
            if channel_id not in acl_streams_map:
                continue
            channel_data = acl_streams_map[channel_id]
            if channel_data.get("stream") is None:
                continue
            available_drops: list[JsonType] = acl_available_drops_map.get(channel_id, [])
            channel.external_update(channel_data, available_drops)

    async def bulk_check_available_drops(
        self, channels: abc.Iterable[Channel]
    ) -> None:
        """
        Verify drop availability for already-ranked online channels in batches.

        This is intentionally separate from bulk_check_online so the advanced
        AvailableDrops check runs only for channels that survive MAX_CHANNELS trimming.
        """
        channel_list = [channel for channel in channels if channel.online]
        if not channel_list:
            return

        operations: list[GQLOperation] = [
            GQL_QUERIES["AvailableDrops"].with_variables(
                {"channelID": str(channel.id)}
            )
            for channel in channel_list
        ]
        tasks: list[asyncio.Task[list[JsonType]]] = [
            asyncio.create_task(self.gql_request(operation_chunk))
            for operation_chunk in chunk(operations, 20)
        ]
        available_map: dict[int, list[JsonType]] = {}
        try:
            for coro in asyncio.as_completed(tasks):
                try:
                    response_list: list[JsonType] = await coro
                except (GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning(f"Bulk available drops check failed: {exc}")
                    continue
                for response_json in response_list:
                    if not isinstance(response_json, dict):
                        continue
                    data = response_json.get("data")
                    if not isinstance(data, dict):
                        continue
                    available_info: JsonType | None = data.get("channel")
                    if isinstance(available_info, dict) and available_info.get("id") is not None:
                        available_map[int(available_info["id"])] = (
                            available_info.get("viewerDropCampaigns") or []
                        )
        except (Exception, asyncio.CancelledError):
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        for channel in channel_list:
            if channel.id in available_map:
                channel.update_available_drops(available_map[channel.id])
            elif self.settings.available_drops_check:
                channel.update_available_drops([])
