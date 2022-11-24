from __future__ import annotations

import re
import sys
import json
import random
import asyncio
import logging
from time import time
from itertools import chain
from functools import partial
from subprocess import CREATE_NO_WINDOW
from collections import abc, deque, OrderedDict
from datetime import datetime, timedelta, timezone
from contextlib import suppress, asynccontextmanager
from typing import Any, Literal, Final, NoReturn, overload, cast, TYPE_CHECKING

import aiohttp
from yarl import URL
try:
    from seleniumwire.request import Request
    from selenium.common.exceptions import WebDriverException
    from seleniumwire.undetected_chromedriver import Chrome, ChromeOptions
except ImportError as exc:
    raise ImportError(
        "You need to install Visual C++ Redist (x86 and x64): "
        "https://support.microsoft.com/en-gb/help/2977003/the-latest-supported-visual-c-downloads"
    ) from exc

from translate import _
from gui import GUIManager
from channel import Channel
from websocket import WebsocketPool
from inventory import DropsCampaign
from exceptions import (
    MinerException,
    ExitRequest,
    LoginException,
    ReloadRequest,
    RequestInvalid,
)
from utils import (
    CHARS_HEX_LOWER,
    chunk,
    timestamp,
    create_nonce,
    task_wrapper,
    first_to_complete,
    OrderedSet,
    AwaitableValue,
    ExponentialBackoff,
)
from constants import (
    BASE_URL,
    CLIENT_ID,
    COOKIES_PATH,
    GQL_OPERATIONS,
    MAX_WEBSOCKETS,
    WATCH_INTERVAL,
    WS_TOPICS_LIMIT,
    DROPS_ENABLED_TAG,
    ANDROID_USER_AGENT,
    State,
    WebsocketTopic,
)

if TYPE_CHECKING:
    from utils import Game
    from gui import LoginForm
    from settings import Settings
    from inventory import TimedDrop
    from constants import JsonType, GQLOperation


logger = logging.getLogger("TwitchDrops")
gql_logger = logging.getLogger("TwitchDrops.gql")


class SkipExtraJsonDecoder(json.JSONDecoder):
    def decode(self, s: str, *args):
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
        self.integrity_token: str
        self.integrity_expires: datetime

    @property
    def integrity_expired(self) -> bool:
        return (
            not hasattr(self, "integrity_expires")
            or datetime.now(timezone.utc) >= self.integrity_expires
        )

    def _hasattrs(self, *attrs: str) -> bool:
        return all(hasattr(self, attr) for attr in attrs)

    def _delattrs(self, *attrs: str) -> None:
        for attr in attrs:
            if hasattr(self, attr):
                delattr(self, attr)

    def clear(self) -> None:
        self._delattrs(
            "user_id",
            "device_id",
            "session_id",
            "access_token",
            "client_version",
            "integrity_token",
            "integrity_expires",
        )
        self._logged_in.clear()

    @staticmethod
    def interceptor(request: Request) -> None:
        if (
            request.method == "POST"
            and request.url == "https://passport.twitch.tv/protected_login"
        ):
            body = request.body.decode("utf-8")
            data = json.loads(body)
            data["client_id"] = CLIENT_ID
            request.body = json.dumps(data).encode("utf-8")
            del request.headers["Content-Length"]
            request.headers["Content-Length"] = str(len(request.body))

    async def _chrome_login(self) -> None:
        gui_print = self._twitch.gui.print
        login_form: LoginForm = self._twitch.gui.login
        coro_unless_closed = self._twitch.gui.coro_unless_closed

        # open the chrome browser on the Twitch's login page
        # use a separate executor to void blocking the event loop
        loop = asyncio.get_running_loop()
        driver: Chrome | None = None
        while True:
            gui_print("Opening Chrome...")
            try:
                version_main = None
                for attempt in range(2):
                    options = ChromeOptions()
                    options.add_argument("--log-level=3")
                    options.add_argument("--disable-web-security")
                    options.add_argument("--allow-running-insecure-content")
                    options.add_argument("--lang=en")
                    options.add_argument("--no-sandbox")
                    options.add_argument("--test-type")
                    options.add_argument("--disable-gpu")
                    options.set_capability("pageLoadStrategy", "eager")
                    try:
                        wire_options: dict[str, Any] = {"proxy": {}}
                        if self._twitch.settings.proxy:
                            wire_options["proxy"]["http"] = str(self._twitch.settings.proxy)
                        driver_coro = loop.run_in_executor(
                            None,
                            lambda: Chrome(
                                options=options,
                                suppress_welcome=True,
                                version_main=version_main,
                                seleniumwire_options=wire_options,
                                service_creationflags=CREATE_NO_WINDOW,
                            )
                        )
                        driver = await coro_unless_closed(driver_coro)
                        break
                    except WebDriverException as exc:
                        message = exc.msg
                        if (
                            message is not None
                            and (
                                match := re.search(
                                    (
                                        r'Chrome version ([\d]+)\n'
                                        r'Current browser version is ((\d+)\.[\d.]+)'
                                    ),
                                    message,
                                )
                            ) is not None
                        ):
                            if not attempt:
                                version_main = int(match.group(3))
                                continue
                            else:
                                raise MinerException(
                                    "Your Chrome browser is out of date\n"
                                    f"Required version: {match.group(1)}\n"
                                    f"Current version: {match.group(2)}"
                                ) from None
                        raise MinerException(
                            "An error occured while boostrapping the Chrome browser"
                        ) from exc
                assert driver is not None
                driver.request_interceptor = self.interceptor
                # driver.set_page_load_timeout(30)
                # page_coro = loop.run_in_executor(None, driver.get, "https://twitch.tv")
                # await coro_unless_closed(page_coro)
                page_coro = loop.run_in_executor(None, driver.get, "https://twitch.tv/login")
                await coro_unless_closed(page_coro)

                # auto login
                # if login_data.username and login_data.password:
                #     driver.find_element("id", "login-username").send_keys(login_data.username)
                #     driver.find_element("id", "password-input").send_keys(login_data.password)
                #     driver.find_element(
                #         "css selector", '[data-a-target="passport-login-button"]'
                #     ).click()
                # token submit button css selectors
                # Button: "screen="two_factor" target="submit_button"
                # Input: <input type="text" autocomplete="one-time-code" data-a-target="tw-input"
                # inputmode="numeric" pattern="[0-9]*" value="">

                # wait for the user to navigate away from the URL, indicating successful login
                # alternatively, they can press on the login button again
                async def url_waiter(driver=driver):
                    while driver.current_url != "https://www.twitch.tv/?no-reload=true":
                        await asyncio.sleep(0.5)

                gui_print(
                    "Complete the login procedure manually by pressing the Login button again."
                )
                await first_to_complete([
                    url_waiter(),
                    coro_unless_closed(login_form.wait_for_login_press()),
                ])

                # cookies = [
                #     {
                #         "domain": ".twitch.tv",
                #         "expiry": 1700000000,
                #         "httpOnly": False,
                #         "name": "auth-token",
                #         "path": "/",
                #         "sameSite": "None",
                #         "secure": True,
                #         "value": "..."
                #     },
                #     ...,
                # ]
                cookies = driver.get_cookies()
                for cookie in cookies:
                    if "twitch.tv" in cookie["domain"] and cookie["name"] == "auth-token":
                        self.access_token = cookie["value"]
                        break
                else:
                    gui_print("Unable to extract authorization token")
            except WebDriverException:
                gui_print(
                    "Chrome window was closed before the login procedure could complete."
                )
            finally:
                if driver is not None:
                    driver.quit()
                    driver = None
            await coro_unless_closed(login_form.wait_for_login_press())

    async def _login(self) -> str:
        logger.debug("Login flow started")
        gui_print = self._twitch.gui.print
        login_form: LoginForm = self._twitch.gui.login

        token_kind: str = ''
        use_chrome: bool = False
        payload: JsonType = {
            "client_id": CLIENT_ID,  # client ID to-be associated with the access token
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
                "Client-Id": CLIENT_ID,
                "Content-Type": "application/json; charset=UTF-8",
                "Host": "passport.twitch.tv",
                "User-Agent": ANDROID_USER_AGENT,
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
                logger.debug(f"Login error code: {error_code}")
                if error_code == 1000:
                    logger.debug("1000: CAPTCHA is required")
                    use_chrome = True
                    break
                elif error_code == 3001:
                    logger.debug("3001: Login failed due to incorrect username or password")
                    gui_print(_("login", "incorrect_login_pass"))
                    login_form.clear(password=True)
                    continue
                elif error_code in (
                    3012,  # Invalid authy token
                    3023,  # Invalid email code
                ):
                    logger.debug("3012/23: Login failed due to incorrect 2FA code")
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
                    logger.debug("3011/22: 2FA token required")
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
                    gui_print(f"Login error code: {error_code}")
                    logger.debug(str(login_response))
                    use_chrome = True
                    break
                else:
                    ext_msg = str(login_response)
                    logger.debug(ext_msg)
                    raise LoginException(ext_msg)
            # Success handling
            if "access_token" in login_response:
                self.access_token = cast(str, login_response["access_token"])
                logger.debug("Access token granted")
                login_form.clear()
                break

        if use_chrome:
            await self._chrome_login()

        if hasattr(self, "access_token"):
            logger.debug("Access token granted")
            return self.access_token
        raise MinerException("Login flow finished without setting the access token")

    def headers(
        self, *, user_agent: str = '', gql: bool = False, integrity: bool = False
    ) -> JsonType:
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Client-Id": CLIENT_ID,
        }
        if user_agent:
            headers["User-Agent"] = user_agent
        if hasattr(self, "session_id"):
            headers["Client-Session-Id"] = self.session_id
        if hasattr(self, "client_version"):
            headers["Client-Version"] = self.client_version
        if hasattr(self, "device_id"):
            headers["X-Device-Id"] = self.device_id
        if gql:
            headers["Origin"] = "https://www.twitch.tv"
            headers["Referer"] = "https://www.twitch.tv/"
            headers["Authorization"] = f"OAuth {self.access_token}"
        if integrity:
            headers["Client-Integrity"] = self.integrity_token
        return headers

    async def validate(self):
        async with self._lock:
            await self._validate()

    async def _validate(self):
        if not hasattr(self, "session_id"):
            self.session_id = create_nonce(CHARS_HEX_LOWER, 16)
        if not self._hasattrs("client_version", "device_id", "access_token", "user_id"):
            session = await self._twitch.get_session()
            jar = cast(aiohttp.CookieJar, session.cookie_jar)
        if not self._hasattrs("client_version", "device_id"):
            async with self._twitch.request(
                "GET", BASE_URL, headers=self.headers()  # (user_agent=ANDROID_USER_AGENT)
            ) as response:
                page_html = await response.text("utf8")
                match = re.search(r'twilightBuildID="([-a-z0-9]+)"', page_html)
            if match is None:
                raise MinerException("Unable to extract client_version")
            self.client_version = match.group(1)
            # doing the request ends up setting the "unique_id" value in the cookie
            cookie = jar.filter_cookies(BASE_URL)
            self.device_id = cookie["unique_id"].value
        if not self._hasattrs("access_token", "user_id"):
            # looks like we're missing something
            login_form: LoginForm = self._twitch.gui.login
            logger.debug("Checking login")
            login_form.update(_("gui", "login", "logging_in"), None)
            for attempt in range(2):
                cookie = jar.filter_cookies(BASE_URL)
                if "auth-token" not in cookie:
                    self.access_token = await self._login()
                    cookie["auth-token"] = self.access_token
                elif not hasattr(self, "access_token"):
                    logger.debug("Restoring session from cookie")
                    self.access_token = cookie["auth-token"].value
                # validate the auth token, by obtaining user_id
                async with self._twitch.request(
                    "GET",
                    "https://id.twitch.tv/oauth2/validate",
                    headers={"Authorization": f"OAuth {self.access_token}"}
                ) as response:
                    status = response.status
                    if status == 401:
                        # the access token we have is invalid - clear the cookie and reauth
                        logger.debug("Restored session is invalid")
                        assert BASE_URL.host is not None
                        jar.clear_domain(BASE_URL.host)
                        continue
                    elif status == 200:
                        validate_response = await response.json()
                        break
            else:
                raise RuntimeError("Login verification failure")
            self.user_id = int(validate_response["user_id"])
            cookie["persistent"] = str(self.user_id)
            logger.debug(f"Login successful, user ID: {self.user_id}")
            login_form.update(_("gui", "login", "logged_in"), self.user_id)
            # update our cookie and save it
            jar.update_cookies(cookie, BASE_URL)
            jar.save(COOKIES_PATH)
        # if not self._hasattrs("integrity_token") or self.integrity_expired:
        #     async with self._twitch.request(
        #         "POST",
        #         "https://gql.twitch.tv/integrity",
        #         headers=self.gql_headers(integrity=False)
        #     ) as response:
        #         self._last_request = datetime.now(timezone.utc)
        #         response_json: JsonType = await response.json()
        #     self.integrity_token = cast(str, response_json["token"])
        #     now = datetime.now(timezone.utc)
        #     expiration = datetime.fromtimestamp(response_json["expiration"] / 1000, timezone.utc)
        #     self.integrity_expires = ((expiration - now) * 0.9) + now
        #     # verify the integrity token's contents for the "is_bad_bot" flag
        #     stripped_token: str = self.integrity_token.split('.')[2] + "=="
        #     messy_json: str = urlsafe_b64decode(stripped_token.encode()).decode(errors="ignore")
        #     match = re.search(r'(.+)(?<="}).+$', messy_json)
        #     if match is None:
        #         raise MinerException("Unable to parse the integrity token")
        #     decoded_header: JsonType = json.loads(match.group(1))
        #     if decoded_header.get("is_bad_bot", "false") != "false":
        #         self._twitch.print(
        #             "Twitch has detected this miner as a \"Bad Bot\". "
        #             "You're proceeding at your own risk!"
        #         )
        #         await asyncio.sleep(8)
        self._logged_in.set()

    def invalidate(self, *, auth: bool = False, integrity: bool = False):
        if auth:
            self._delattrs("access_token")
        if integrity:
            self._delattrs("client_version")
            self.integrity_expires = datetime.now(timezone.utc)


class Twitch:
    def __init__(self, settings: Settings):
        self.settings: Settings = settings
        # State management
        self._state: State = State.IDLE
        self._state_change = asyncio.Event()
        self.wanted_games: dict[Game, int] = {}
        self.inventory: list[DropsCampaign] = []
        self._drops: dict[str, TimedDrop] = {}
        self._mnt_triggers: deque[datetime] = deque()
        # Session and auth
        self._session: aiohttp.ClientSession | None = None
        self._auth_state: _AuthState = _AuthState(self)
        # GUI
        self.gui = GUIManager(self)
        # Storing and watching channels
        self.channels: OrderedDict[int, Channel] = OrderedDict()
        self.watching_channel: AwaitableValue[Channel] = AwaitableValue()
        self._watching_task: asyncio.Task[None] | None = None
        self._watching_restart = asyncio.Event()
        self._drop_update: asyncio.Future[bool] | None = None
        # Websocket
        self.websocket = WebsocketPool(self)
        # Maintenance task
        self._mnt_task: asyncio.Task[None] | None = None

    async def get_session(self) -> aiohttp.ClientSession:
        if (session := self._session) is not None:
            if session.closed:
                raise RuntimeError("Session is closed")
            return session
        # obtain the latest Chrome user agent from a Github project
        async with aiohttp.request(
            "GET", "https://jnrbsn.github.io/user-agents/user-agents.json"
        ) as response:
            agents = await response.json()
        if sys.platform == "win32":
            chrome_agent = random.choice(agents[:3])
        elif sys.platform == "linux":
            chrome_agent = random.choice(agents[7:11])
        # load in cookies
        cookie_jar = aiohttp.CookieJar()
        if COOKIES_PATH.exists():
            cookie_jar.load(COOKIES_PATH)
        # create session, limited to 50 connections at maximum
        connector = aiohttp.TCPConnector(limit=50)
        self._session = aiohttp.ClientSession(
            connector=connector,
            cookie_jar=cookie_jar,
            headers={"User-Agent": chrome_agent},
            timeout=aiohttp.ClientTimeout(connect=5, total=10),
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
            cookie_jar.save(COOKIES_PATH)
            await self._session.close()
            self._session = None
        self._drop_update = None
        self._drops.clear()
        self.channels.clear()
        self.inventory.clear()
        self._auth_state.clear()
        self.wanted_games.clear()
        self._mnt_triggers.clear()
        # wait at least half a second + whatever it takes to complete the closing
        # this allows aiohttp to safely close the session
        await asyncio.sleep(start_time + 0.5 - time())

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

    def print(self, *args, **kwargs):
        """
        Can be used to print messages within the GUI.
        """
        self.gui.print(*args, **kwargs)

    def save(self, *, force: bool = False) -> None:
        """
        Saves the application state.
        """
        self.gui.save(force=force)
        self.settings.save(force=force)

    def get_priority(self, channel: Channel) -> int:
        """
        Return a priority number for a given channel.

        Higher number, higher priority.
        Priority 0 is given to channels streaming a game not on the priority list.
        Priority -1 is given to OFFLINE channels, or channels streaming no particular games.
        """
        if (game := channel.game) is None:
            # None when OFFLINE or no game set
            return -1
        elif game not in self.wanted_games:
            return 0
        return self.wanted_games[game]

    @staticmethod
    def _viewers_key(channel: Channel) -> int:
        if (viewers := channel.viewers) is not None:
            return viewers
        return -1

    async def run(self):
        while True:
            try:
                await self._run()
                break
            except ReloadRequest:
                await self.shutdown()
            except ExitRequest:
                break
            except aiohttp.ContentTypeError as exc:
                raise MinerException(_("login", "unexpected_content")) from exc

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
            WebsocketTopic("User", "CommunityPoints", auth_state.user_id, self.process_points),
        ])
        full_cleanup: bool = False
        channels: Final[OrderedDict[int, Channel]] = self.channels
        self.change_state(State.INVENTORY_FETCH)
        while True:
            if self._state is State.IDLE:
                self.gui.status.update(_("gui", "status", "idle"))
                self.stop_watching()
                # clear the flag and wait until it's set again
                self._state_change.clear()
            elif self._state is State.INVENTORY_FETCH:
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
                priorities = self.gui.settings.priorities()
                exclude = self.settings.exclude
                priority = self.settings.priority
                priority_only = self.settings.priority_only
                in_one_hour = datetime.now(timezone.utc) + timedelta(hours=1)
                for campaign in self.inventory:
                    game = campaign.game
                    if (
                        game not in self.wanted_games  # isn't already there
                        and game.name not in exclude  # and isn't excluded
                        # and isn't excluded by priority_only
                        and (not priority_only or game.name in priority)
                        # and can be progressed within the next hour
                        and campaign.can_earn_within(in_one_hour)
                    ):
                        # non-excluded games with no priority are placed last, below priority ones
                        self.wanted_games[game] = priorities.get(game.name, 0)
                full_cleanup = True
                self.restart_watching()
                self.change_state(State.CHANNELS_CLEANUP)
            elif self._state is State.CHANNELS_CLEANUP:
                self.gui.status.update(_("gui", "status", "cleanup"))
                if not self.wanted_games or full_cleanup:
                    # no games selected or we're doing full cleanup: remove everything
                    to_remove: list[Channel] = list(channels.values())
                else:
                    # remove all channels that:
                    to_remove = [
                        channel
                        for channel in channels.values()
                        if (
                            not channel.acl_based  # aren't ACL-based
                            and (
                                channel.offline  # and are offline
                                # or online but aren't streaming the game we want anymore
                                or (channel.game is None or channel.game not in self.wanted_games)
                            )
                        )
                    ]
                full_cleanup = False
                if to_remove:
                    self.websocket.remove_topics(
                        WebsocketTopic.as_str("Channel", "StreamState", channel.id)
                        for channel in to_remove
                    )
                    for channel in to_remove:
                        del channels[channel.id]
                        channel.remove()
                    del to_remove
                if self.wanted_games:
                    self.change_state(State.CHANNELS_FETCH)
                else:
                    # with no games available, we switch to IDLE after cleanup
                    self.gui.print(_("status", "no_campaign"))
                    self.change_state(State.IDLE)
            elif self._state is State.CHANNELS_FETCH:
                self.gui.status.update(_("gui", "status", "gathering"))
                # start with all current channels
                new_channels: OrderedSet[Channel] = OrderedSet(self.channels.values())
                # gather and add ACL channels from campaigns
                # NOTE: we consider only campaigns that can be progressed
                # NOTE: we use another set so that we can set them online separately
                no_acl: set[Game] = set()
                acl_channels: OrderedSet[Channel] = OrderedSet()
                in_one_hour = datetime.now(timezone.utc) + timedelta(hours=1)
                for campaign in self.inventory:
                    if (
                        campaign.game in self.wanted_games
                        and campaign.can_earn_within(in_one_hour)
                    ):
                        if campaign.allowed_channels:
                            acl_channels.update(campaign.allowed_channels)
                        else:
                            no_acl.add(campaign.game)
                # remove all ACL channels that already exist from the other set
                acl_channels.difference_update(new_channels)
                # use the other set to set them online if possible
                if acl_channels:
                    await asyncio.gather(*(channel.check_online() for channel in acl_channels))
                # finally, add them as new channels
                new_channels.update(acl_channels)
                for game in no_acl:
                    # for every campaign without an ACL, for it's game,
                    # add a list of live channels with drops enabled
                    new_channels.update(await self.get_live_streams(game))
                # sort them descending by viewers, by priority and by game priority
                # NOTE: We can drop OrderedSet now because there's no more channels being added
                ordered_channels: list[Channel] = sorted(
                    new_channels, key=self._viewers_key, reverse=True
                )
                ordered_channels.sort(key=lambda ch: ch.acl_based, reverse=True)
                ordered_channels.sort(key=self.get_priority, reverse=True)
                # ensure that we won't end up with more channels than we can handle
                # NOTE: we substract 2 due to the two base topics always being added:
                # channel points gain and drop update subscriptions
                # NOTE: we trim from the end because that's where the non-priority,
                # offline (or online but low viewers) channels end up
                max_channels = MAX_WEBSOCKETS * WS_TOPICS_LIMIT - 2
                to_remove = ordered_channels[max_channels:]
                ordered_channels = ordered_channels[:max_channels]
                if to_remove:
                    # tracked channels and gui are cleared below, so no need to do it here
                    # just make sure to unsubscribe from their topics
                    self.websocket.remove_topics(
                        WebsocketTopic.as_str("Channel", "StreamState", channel.id)
                        for channel in to_remove
                    )
                    del to_remove
                # set our new channel list
                channels.clear()
                self.gui.channels.clear()
                for channel in ordered_channels:
                    channels[channel.id] = channel
                    channel.display(add=True)
                # subscribe to these channel's state updates
                self.websocket.add_topics([
                    WebsocketTopic(
                        "Channel", "StreamState", channel_id, self.process_stream_state
                    )
                    for channel_id in channels
                ])
                # relink watching channel after cleanup,
                # or stop watching it if it no longer qualifies
                # NOTE: this replaces 'self.watching_channel's internal value with the new object
                watching_channel = self.watching_channel.get_with_default(None)
                if watching_channel is not None:
                    new_watching = channels.get(watching_channel.id)
                    if new_watching is not None and self.can_watch(new_watching):
                        self.watch(new_watching)
                    else:
                        # we've removed a channel we were watching
                        self.stop_watching()
                # pre-display the active drop with a substracted minute
                for channel in channels.values():
                    # check if there's any channels we can watch first
                    if self.can_watch(channel):
                        if (active_drop := self.get_active_drop(channel)) is not None:
                            active_drop.display(countdown=False, subone=True)
                        break
                self.change_state(State.CHANNEL_SWITCH)
            elif self._state is State.CHANNEL_SWITCH:
                self.gui.status.update(_("gui", "status", "switching"))
                # Change into the selected channel, stay in the watching channel,
                # or select a new channel that meets the required conditions
                new_watching = None
                selected_channel = self.gui.channels.get_selection()
                if selected_channel is not None and self.can_watch(selected_channel):
                    # selected channel is checked first, and set as long as we can watch it
                    new_watching = selected_channel
                else:
                    # other channels additionally need to have a good reason
                    # for a switch (including the watching one)
                    # NOTE: we need to sort the channels every time because one channel
                    # can end up streaming any game - channels aren't game-tied
                    for channel in sorted(channels.values(), key=self.get_priority, reverse=True):
                        if self.can_watch(channel) and self.should_switch(channel):
                            new_watching = channel
                            break
                watching_channel = self.watching_channel.get_with_default(None)
                if new_watching is not None:
                    # if we have a better switch target - do so
                    self.watch(new_watching)
                    self.gui.status.update(
                        _("gui", "status", "watching").format(channel=new_watching.name)
                    )
                    # break the state change chain by clearing the flag
                    self._state_change.clear()
                elif watching_channel is not None:
                    # otherwise, continue watching what we had before
                    self.gui.status.update(
                        _("gui", "status", "watching").format(channel=watching_channel.name)
                    )
                    # break the state change chain by clearing the flag
                    self._state_change.clear()
                else:
                    # not watching anything and there isn't anything to watch either
                    self.gui.print(_("status", "no_channel"))
                    self.change_state(State.IDLE)
            elif self._state is State.EXIT:
                self.gui.status.update(_("gui", "status", "exiting"))
                # we've been requested to exit the application
                break
            await self._state_change.wait()

    async def _watch_sleep(self, delay: float) -> None:
        # we use wait_for here to allow an asyncio.sleep-like that can be ended prematurely
        self._watching_restart.clear()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._watching_restart.wait(), timeout=delay)

    @task_wrapper
    async def _watch_loop(self) -> NoReturn:
        interval = WATCH_INTERVAL.total_seconds()
        while True:
            channel = await self.watching_channel.get()
            succeeded = await channel.send_watch()
            if not succeeded:
                # this usually means the campaign expired in the middle of mining
                # NOTE: the maintenance task should switch the channel right after this happens
                await self._watch_sleep(60)
                continue
            last_watch = time()
            self._drop_update = asyncio.Future()
            use_active = False
            try:
                handled = await asyncio.wait_for(self._drop_update, timeout=10)
            except asyncio.TimeoutError:
                # there was no websocket update within 10s
                handled = False
                use_active = True
            self._drop_update = None
            if not handled:
                # websocket update timed out, or the update was for an unrelated drop
                if not use_active:
                    # we need to use GQL to get the current progress
                    context = await self.gql_request(GQL_OPERATIONS["CurrentDrop"])
                    drop_data: JsonType | None = (
                        context["data"]["currentUser"]["dropCurrentSession"]
                    )
                    if drop_data is not None:
                        drop_id = drop_data["dropID"]
                        drop = self._drops.get(drop_id)
                        if drop is None:
                            use_active = True
                            logger.error(f"Missing drop: {drop_id}")
                        elif not drop.can_earn(channel):
                            use_active = True
                        else:
                            drop.update_minutes(drop_data["currentMinutesWatched"])
                            drop.display()
                    else:
                        use_active = True
                if use_active:
                    # Sometimes, even GQL fails to give us the correct drop.
                    # In that case, we can use the locally cached inventory to try
                    # and put together the drop that we're actually mining right now
                    # NOTE: get_active_drop uses the watching channel by default,
                    # so there's no point to pass it here
                    if (drop := self.get_active_drop()) is not None:
                        drop.bump_minutes()
                        drop.display()
            await self._watch_sleep(last_watch + interval - time())

    @task_wrapper
    async def _maintenance_task(self) -> None:
        claim_period = timedelta(minutes=30)
        max_period = timedelta(hours=1)
        now = datetime.now(timezone.utc)
        next_period = now + max_period
        while True:
            # exit if there's no need to repeat the loop
            now = datetime.now(timezone.utc)
            if now >= next_period:
                break
            next_trigger = min(now + claim_period, next_period)
            trigger_switch = False
            while self._mnt_triggers and (switch_trigger := self._mnt_triggers[0]) <= next_trigger:
                trigger_switch = True
                self._mnt_triggers.popleft()
                next_trigger = switch_trigger
            await asyncio.sleep((next_trigger - now).total_seconds())
            # exit after waiting, before the actions
            now = datetime.now(timezone.utc)
            if now >= next_period:
                break
            if trigger_switch:
                self.change_state(State.CHANNEL_SWITCH)
            # ensure that we don't have unclaimed points bonus
            channel = self.watching_channel.get_with_default(None)
            if channel is not None:
                try:
                    await channel.claim_bonus()
                except Exception:
                    pass  # we intentionally silently skip anything else
            # this triggers this task restart every (up to) 60 minutes
        self.change_state(State.INVENTORY_FETCH)

    def can_watch(self, channel: Channel) -> bool:
        """
        Determines if the given channel qualifies as a watching candidate.
        """
        if not self.wanted_games:
            return False
        # exit early if
        if (
            not channel.online  # stream is offline
            or not channel.drops_enabled  # drops aren't enabled
            # there's no game or it's not one of the games we've selected
            or (game := channel.game) is None or game not in self.wanted_games
        ):
            return False
        # check if we can progress any campaign for the played game
        for campaign in self.inventory:
            if campaign.game == game and campaign.can_earn(channel):
                return True
        return False

    def should_switch(self, channel: Channel) -> bool:
        """
        Determines if the given channel qualifies as a switch candidate.
        """
        watching_channel = self.watching_channel.get_with_default(None)
        if watching_channel is None:
            return True
        channel_order = self.get_priority(channel)
        watching_order = self.get_priority(watching_channel)
        return (
            # this channel's game is higher order than the watching one's
            channel_order > watching_order
            or channel_order == watching_order  # or the order is the same
            # and this channel is ACL-based and the watching channel isn't
            and channel.acl_based > watching_channel.acl_based
        )

    def watch(self, channel: Channel):
        self.gui.channels.set_watching(channel)
        self.watching_channel.set(channel)

    def stop_watching(self):
        self.gui.progress.stop_timer()
        self.gui.channels.clear_watching()
        self.watching_channel.clear()

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
                channel.set_online()
            else:
                viewers = message["viewers"]
                channel.viewers = viewers
                channel.display()
                # logger.debug(f"{channel.name} viewers: {viewers}")
        elif msg_type == "stream-down":
            channel.set_offline()
        elif msg_type == "stream-up":
            channel.set_online()
        elif msg_type == "commercial":
            # skip these
            pass
        else:
            logger.warning(f"Unknown stream state: {msg_type}")

    def on_online(self, channel: Channel):
        """
        Called by a Channel when it goes online (after pending).
        """
        logger.debug(f"{channel.name} goes ONLINE")
        if (
            self.can_watch(channel)  # we can watch the channel that just got ONLINE
            and self.should_switch(channel)  # and we should!
        ):
            self.watch(channel)
            self.gui.print(_("status", "goes_online").format(channel=channel.name))
            self.gui.status.update(
                _("gui", "status", "watching").format(channel=channel.name)
            )

    def on_offline(self, channel: Channel):
        """
        Called by a Channel when it goes offline.
        """
        # change the channel if we're currently watching it
        watching_channel = self.watching_channel.get_with_default(None)
        if watching_channel is not None and watching_channel == channel:
            self.gui.print(_("status", "goes_offline").format(channel=channel.name))
            self.change_state(State.CHANNEL_SWITCH)
        else:
            logger.debug(f"{channel.name} goes OFFLINE")

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
        if msg_type == "drop-claim":
            if drop is None:
                logger.error(
                    f"Received a drop claim ID for a non-existing drop: {drop_id}\n"
                    f"Drop claim ID: {message['data']['drop_instance_id']}"
                )
                return
            drop.update_claim(message["data"]["drop_instance_id"])
            campaign = drop.campaign
            mined = await drop.claim()
            drop.display()
            if mined:
                claim_text = (
                    f"{drop.rewards_text()} "
                    f"({campaign.claimed_drops}/{campaign.total_drops})"
                )
                self.gui.print(_("status", "claimed_drop").format(drop=claim_text))
                self.gui.tray.notify(claim_text, _("gui", "tray", "notification_title"))
            else:
                logger.error(f"Drop claim failed! Drop ID: {drop_id}")
            # About 4-20s after claiming the drop, next drop can be started
            # by re-sending the watch payload. We can test for it by fetching the current drop
            # via GQL, and then comparing drop IDs.
            await asyncio.sleep(4)
            for attempt in range(8):
                context = await self.gql_request(GQL_OPERATIONS["CurrentDrop"])
                drop_data: JsonType | None = (
                    context["data"]["currentUser"]["dropCurrentSession"]
                )
                if drop_data is None or drop_data["dropID"] != drop.id:
                    break
                await asyncio.sleep(2)
            if campaign.remaining_drops:
                self.restart_watching()
            else:
                self.change_state(State.INVENTORY_FETCH)
            return
        assert msg_type == "drop-progress"
        if self._drop_update is None:
            # we aren't actually waiting for a progress update right now, so we can just
            # ignore the event this time
            return
        elif drop is not None and drop.can_earn(self.watching_channel.get_with_default(None)):
            # the received payload is for the drop we expected
            drop.update_minutes(message["data"]["current_progress_min"])
            drop.display()
            # Let the watch loop know we've handled it here
            self._drop_update.set_result(True)
        else:
            # Sometimes, the drop update we receive doesn't actually match what we're mining.
            # This is a Twitch bug workaround: signal the watch loop to use GQL
            # to get the current drop progress instead.
            self._drop_update.set_result(False)
        self._drop_update = None

    @task_wrapper
    async def process_points(self, user_id: int, message: JsonType):
        # Example payloads:
        # {
        #     "type": "points-earned",
        #     "data": {
        #         "timestamp": "YYYY-MM-DDTHH:MM:SS.UUUUUUUUUZ",
        #         "channel_id": "123456789",
        #         "point_gain": {
        #             "user_id": "12345678",
        #             "channel_id": "123456789",
        #             "total_points": 10,
        #             "baseline_points": 10,
        #             "reason_code": "WATCH",
        #             "multipliers": []
        #         },
        #         "balance": {
        #             "user_id": "12345678",
        #             "channel_id": "123456789",
        #             "balance": 12345
        #         }
        #     }
        # }
        # {
        #     "type": "claim-available",
        #     "data": {
        #         "timestamp":"YYYY-MM-DDTHH:MM:SS.UUUUUUUUUZ",
        #         "claim": {
        #             "id": "4ae6fefd-1234-40ae-ad3d-92254c576a91",
        #             "user_id": "12345678",
        #             "channel_id": "123456789",
        #             "point_gain": {
        #                 "user_id": "12345678",
        #                 "channel_id": "123456789",
        #                 "total_points": 50,
        #                 "baseline_points": 50,
        #                 "reason_code": "CLAIM",
        #                 "multipliers": []
        #             },
        #             "created_at": "YYYY-MM-DDTHH:MM:SSZ"
        #         }
        #     }
        # }
        msg_type = message["type"]
        if msg_type == "points-earned":
            data: JsonType = message["data"]
            channel: Channel | None = self.channels.get(int(data["channel_id"]))
            points: int = data["point_gain"]["total_points"]
            balance: int = data["balance"]["balance"]
            if channel is not None:
                channel.points = balance
                channel.display()
            self.gui.print(
                _("status", "earned_points").format(points=f"{points:3}", balance=balance)
            )
        elif msg_type == "claim-available":
            claim_data = message["data"]["claim"]
            points = claim_data["point_gain"]["total_points"]
            await self.claim_points(claim_data["channel_id"], claim_data["id"])
            self.gui.print(_("status", "claimed_points").format(points=points))

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
            try:
                response: aiohttp.ClientResponse | None = None
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
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
                # just so that quick retries that often happen, aren't shown
                if backoff.steps > 1:
                    self.print(_("error", "no_connection").format(seconds=round(delay)))
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
        while True:
            try:
                auth_state = await self.get_auth()
                async with self.request(
                    "POST",
                    "https://gql.twitch.tv/gql",
                    json=ops,
                    headers=auth_state.headers(gql=True),
                    invalidate_after=getattr(auth_state, "integrity_expires", None),
                ) as response:
                    response_json: JsonType | list[JsonType] = await response.json()
            except RequestInvalid:
                continue
            gql_logger.debug(f"GQL Response: {response_json}")
            orig_response = response_json
            if isinstance(response_json, list):
                response_list = response_json
            else:
                response_list = [response_json]
            for response_json in response_list:
                if "errors" in response_json and response_json["errors"]:
                    if (
                        "message" in response_json["errors"]
                        and response_json["errors"]["message"] == "service timeout"
                    ):
                        await asyncio.sleep(1)
                        continue
                    raise MinerException(f"GQL error: {response_json['errors']}")
            return orig_response

    def _merge_data(self, primary_data: JsonType, secondary_data: JsonType) -> JsonType:
        merged = {}
        for key in set(chain(primary_data.keys(), secondary_data.keys())):
            in_primary = key in primary_data
            in_secondary = key in secondary_data
            if in_primary and in_secondary:
                vp = primary_data[key]
                vs = secondary_data[key]
                if not isinstance(vp, type(vs)) or not isinstance(vs, type(vp)):
                    raise MinerException("Inconsistent merge data")
                if isinstance(vp, dict):  # both are dicts
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
        response_list: list[JsonType] = await self.gql_request(
            [
                GQL_OPERATIONS["CampaignDetails"].with_variables(
                    {"channelLogin": str(auth_state.user_id), "dropID": cid}
                )
                for cid in campaign_ids
            ]
        )
        fetched_data: dict[str, JsonType] = {
            (campaign_data := response_json["data"]["user"]["dropCampaign"])["id"]: campaign_data
            for response_json in response_list
        }
        return self._merge_data(campaign_ids, fetched_data)

    async def fetch_inventory(self) -> None:
        status_update = self.gui.status.update
        status_update(_("gui", "status", "fetching_inventory"))
        # fetch in-progress campaigns (inventory)
        response = await self.gql_request(GQL_OPERATIONS["Inventory"])
        inventory: JsonType = response["data"]["currentUser"]["inventory"]
        ongoing_campaigns: list[JsonType] = inventory["dropCampaignsInProgress"] or []
        # this contains claimed benefit edge IDs, not drop IDs
        claimed_benefits: dict[str, datetime] = {
            b["id"]: timestamp(b["lastAwardedAt"]) for b in inventory["gameEventDrops"]
        }
        inventory_data: dict[str, JsonType] = {c["id"]: c for c in ongoing_campaigns}
        # fetch general available campaigns data (campaigns)
        response = await self.gql_request(GQL_OPERATIONS["Campaigns"])
        available_list: list[JsonType] = response["data"]["currentUser"]["dropCampaigns"] or []
        applicable_statuses = ("ACTIVE", "UPCOMING")
        available_campaigns: dict[str, JsonType] = {
            c["id"]: c
            for c in available_list
            if c["status"] in applicable_statuses  # that are currently not expired
        }
        # fetch detailed data for each campaign, in chunks
        # specifically use an intermediate list per a Python bug
        # https://github.com/python/cpython/issues/88342
        status_update(_("gui", "status", "fetching_campaigns"))
        for chunk_coro in asyncio.as_completed(
            [
                self.fetch_campaigns(campaigns_chunk)
                for campaigns_chunk in chunk(available_campaigns.items(), 20)
            ]
        ):
            chunk_campaigns_data = await chunk_coro
            # merge the inventory and campaigns datas together
            inventory_data = self._merge_data(inventory_data, chunk_campaigns_data)
        # use the merged data to create campaign objects
        campaigns: list[DropsCampaign] = [
            DropsCampaign(self, campaign_data, claimed_benefits)
            for campaign_data in inventory_data.values()
        ]
        campaigns.sort(key=lambda c: c.active, reverse=True)
        campaigns.sort(key=lambda c: c.upcoming and c.starts_at or c.ends_at)
        campaigns.sort(key=lambda c: c.linked, reverse=True)
        self._drops.clear()
        self.gui.inv.clear()
        self.inventory.clear()
        switch_triggers: set[datetime] = set()
        for i, campaign in enumerate(campaigns, start=1):
            status_update(
                _("gui", "status", "adding_campaigns").format(counter=f"({i}/{len(campaigns)})")
            )
            self._drops.update({drop.id: drop for drop in campaign.drops})
            switch_triggers.add(campaign.starts_at)
            switch_triggers.add(campaign.ends_at)
            # NOTE: this fetches pictures from the CDN, so might be slow without a cache
            await self.gui.inv.add_campaign(campaign)
            # this is needed here explicitly, because images aren't always fetched
            if self.gui.close_requested:
                raise ExitRequest()
            self.inventory.append(campaign)
        self._mnt_triggers.clear()
        self._mnt_triggers.extend(sorted(switch_triggers))
        # trim out all triggers that we're already past
        now = datetime.now(timezone.utc)
        while self._mnt_triggers and self._mnt_triggers[0] <= now:
            self._mnt_triggers.popleft()
        # NOTE: maintenance task is restarted at the end of each inventory fetch
        if self._mnt_task is not None and not self._mnt_task.done():
            self._mnt_task.cancel()
        self._mnt_task = asyncio.create_task(self._maintenance_task())

    def get_active_drop(self, channel: Channel | None = None) -> TimedDrop | None:
        if not self.wanted_games:
            return None
        watching_channel = self.watching_channel.get_with_default(channel)
        if watching_channel is None:
            # if we aren't watching anything, we can't earn any drops
            return None
        watching_game: Game | None = watching_channel.game
        if watching_game is None:
            # if the channel isn't playing anything in particular, we can't determine the drop
            return None
        drops: list[TimedDrop] = []
        for campaign in self.inventory:
            if (
                campaign.game == watching_game  # campaign's game matches watching game
                and campaign.can_earn(watching_channel)  # can be earned on this channel
            ):
                # add only the drops we can actually earn
                drops.extend(drop for drop in campaign.drops if drop.can_earn(watching_channel))
        if drops:
            drops.sort(key=lambda d: d.remaining_minutes)
            return drops[0]
        return None

    async def get_live_streams(self, game: Game, *, limit: int = 30) -> list[Channel]:
        response = await self.gql_request(
            GQL_OPERATIONS["GameDirectory"].with_variables({
                "limit": limit,
                "name": game.name,
                "options": {
                    "includeRestricted": ["SUB_ONLY_LIVE"],
                    "tags": [DROPS_ENABLED_TAG],
                },
            })
        )
        return [
            Channel.from_directory(self, stream_channel_data["node"])
            for stream_channel_data in response["data"]["game"]["streams"]["edges"]
        ]

    async def claim_points(self, channel_id: str | int, claim_id: str) -> None:
        await self.gql_request(
            GQL_OPERATIONS["ClaimCommunityPoints"].with_variables(
                {"input": {"channelID": str(channel_id), "claimID": claim_id}}
            )
        )
