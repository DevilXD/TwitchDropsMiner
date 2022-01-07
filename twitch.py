from __future__ import annotations

import os
import asyncio
import logging
import traceback
from yarl import URL
from time import time
from itertools import chain
from functools import partial
from typing import Any, Callable, Iterable, Optional, Union, List, Dict, Set, cast, TYPE_CHECKING

try:
    import aiohttp
except ImportError:
    raise ImportError("You have to run 'python -m pip install aiohttp' first")

from channel import Channel
from gui import GUIManager, LoginData
from websocket import WebsocketPool, task_wrapper
from inventory import DropsCampaign, Game, TimedDrop
from exceptions import LoginException, CaptchaRequired
from constants import (
    State,
    JsonType,
    WebsocketTopic,
    CLIENT_ID,
    USER_AGENT,
    COOKIES_PATH,
    AUTH_URL,
    GQL_URL,
    WATCH_INTERVAL,
    GQL_OPERATIONS,
    DROPS_ENABLED_TAG,
    GQLOperation,
)

if TYPE_CHECKING:
    from main import ParsedArgs


logger = logging.getLogger("TwitchDrops")
gql_logger = logging.getLogger("TwitchDrops.gql")


def debug_log(file, category: str, drop: TimedDrop):
    print(
        format(time(), ".6f"),
        drop.id,
        category,
        drop.current_minutes,
        drop.is_claimed,
        sep='\t',
        file=file,
    )


class Twitch:
    def __init__(self, options: ParsedArgs):
        self._options = options
        # GUI
        self.gui = GUIManager(self)
        # Cookies, session and auth
        cookie_jar = aiohttp.CookieJar()
        if os.path.isfile(COOKIES_PATH):
            cookie_jar.load(COOKIES_PATH)
        self._session = aiohttp.ClientSession(
            cookie_jar=cookie_jar,
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(connect=5, total=10),
        )
        self._access_token: Optional[str] = None
        self._user_id: Optional[int] = None
        self._is_logged_in = asyncio.Event()
        # State management
        self._state: State = State.INVENTORY_FETCH
        self._state_change = asyncio.Event()
        self.inventory: List[DropsCampaign] = []  # inventory
        # Storing and watching channels
        self.channels: Dict[int, Channel] = {}
        self._watching_channel: Optional[Channel] = None
        self._watching_task: Optional[asyncio.Task[Any]] = None
        self._last_watch = time() - 60
        self._drop_update: Optional[asyncio.Future[bool]] = None
        # Websocket
        self.websocket = WebsocketPool(self)
        # Runner task
        self._main_task: Optional[asyncio.Task[None]] = None

    def wait_until_login(self):
        return self._is_logged_in.wait()

    def change_state(self, state: State) -> None:
        self._state = state
        self._state_change.set()

    def state_change(self, state: State) -> Callable[[], None]:
        # this is identical to change_state, but defers the call
        # perfect for GUI usage
        return partial(self.change_state, state)

    def request_close(self):
        """
        Called when the application is requested to close,
        usually by the console or application window being closed.
        """
        self.stop()

    def start(self):
        self._loop = loop = asyncio.get_event_loop()
        self._main_task = loop.create_task(self._run())

        try:
            loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            # happens when the user requests close
            pass
        except KeyboardInterrupt:
            # KeyboardInterrupt causes run_until_complete to exit, but without cancelling the task.
            # The loop stops and thus the task gets frozen, until the loop runs again.
            # Because we don't want anything from there to actually run during cleanup,
            # we need to explicitly cancel the task ourselves here.
            self.stop()
        except CaptchaRequired:
            self.gui.prevent_close()
            self.gui.print(
                "Your login attempt was denied by CAPTCHA.\nPlease try again in +12 hours."
            )
        except Exception:
            self.gui.prevent_close()
            self.gui.print("Fatal error encountered:\n")
            self.gui.print(traceback.format_exc())
        finally:
            loop.run_until_complete(self.close())
            loop.run_until_complete(loop.shutdown_asyncgens())
        if not self.gui.close_requested:
            self.gui.print(
                "\nApplication Terminated.\nClose the window to exit the application."
            )
        loop.run_until_complete(self.gui.wait_until_closed())
        loop.close()

    def stop(self):
        if self._main_task is not None:
            self._main_task.cancel()
            self._main_task = None

    async def close(self):
        start_time = time()
        self.gui.print("Exiting...")
        self.stop_watching()
        self._session.cookie_jar.save(COOKIES_PATH)  # type: ignore
        await self._session.close()
        await self.websocket.stop()
        # wait at least one full second + whatever it takes to complete the closing
        # this allows aiohttp to safely close the session
        await asyncio.sleep(start_time + 1 - time())

    def is_watching(self, channel: Channel) -> bool:
        return self._watching_channel is not None and self._watching_channel == channel

    async def _run(self):
        """
        Main method that runs the whole client.

        Here, we manage several things, specifically:
        • Fetching the drops inventory to make sure that everything we can claim, is claimed
        • Selecting a stream to watch, and watching it
        • Changing the stream that's being watched if necessary
        """
        self.gui.start()
        await self.check_login()
        # Add default topics
        assert self._user_id is not None
        self.websocket.add_topics([
            WebsocketTopic("User", "Drops", self._user_id, self.process_drops),
            WebsocketTopic("User", "CommunityPoints", self._user_id, self.process_points),
        ])
        games: Set[Game] = set()
        selected_game: Optional[Game] = None
        self.change_state(State.INVENTORY_FETCH)
        while True:
            if self._state is State.INVENTORY_FETCH:
                # Claim the drops we can
                await self.fetch_inventory()
                games.clear()
                for campaign in self.inventory:
                    if campaign.status == "UPCOMING":
                        # we have no use in processing upcoming campaigns here
                        continue
                    for drop in campaign.timed_drops.values():
                        if drop.can_earn:
                            games.add(campaign.game)
                        if drop.can_claim:
                            await drop.claim()
                self.change_state(State.GAME_SELECT)
            elif self._state is State.GAME_SELECT:
                # 'games' has all games we want to farm drops for
                # if it's empty, there's no point in continuing
                if not games:
                    self.gui.print("No active campaigns to farm drops for.")
                    return
                # only start the websocket after we confirm there are drops to mine
                await self.websocket.start()
                self.gui.games.set_games(games)
                selected_game = self.gui.games.get_selection()
                # pre-display the active drop without a countdown
                active_drop = self.get_active_drop(selected_game)
                if active_drop is not None:
                    active_drop.display(countdown=False)
                self.change_state(State.CHANNEL_CLEANUP)
            elif self._state is State.CHANNEL_FETCH:
                if selected_game is None:
                    self.change_state(State.GAME_SELECT)
                else:
                    # get a list of all live channels with drops enabled
                    live_streams: List[Channel] = await self.get_live_streams(
                        selected_game, [DROPS_ENABLED_TAG]
                    )
                    # filter out ones we already have
                    live_streams = [ch for ch in live_streams if ch.id not in self.channels]
                    for channel in live_streams:
                        self.channels[channel.id] = channel
                        channel.display()
                    # load points
                    # asyncio.gather(*(channel.claim_bonus() for channel in live_streams))
                    # Sub to these channel updates
                    topics: List[WebsocketTopic] = [
                        WebsocketTopic(
                            "Channel", "VideoPlayback", channel_id, self.process_stream_state
                        )
                        for channel_id in self.channels
                    ]
                    self.websocket.add_topics(topics)
                    self.change_state(State.CHANNEL_SWITCH)
            elif self._state is State.CHANNEL_CLEANUP:
                # remove all channels that are offline,
                # or aren't streaming the game we want anymore
                to_remove = [
                    channel for channel in self.channels.values()
                    if not (channel.online or channel.pending_online)
                    or channel.game is None or channel.game != selected_game
                ]
                self.websocket.remove_topics(
                    WebsocketTopic.as_str("Channel", "VideoPlayback", channel.id)
                    for channel in to_remove
                )
                for channel in to_remove:
                    del self.channels[channel.id]
                    channel.remove()
                self.change_state(State.CHANNEL_FETCH)
            elif self._state is State.CHANNEL_SWITCH:
                if selected_game is None:
                    self.change_state(State.GAME_SELECT)
                else:
                    # Change into the selected channel
                    channels: Iterable[Channel]
                    selected_channel = self.gui.channels.get_selection()
                    if selected_channel is not None:
                        self.gui.channels.clear_selection()
                        channels = chain([selected_channel], self.channels.values())
                    else:
                        channels = self.channels.values()
                    # If there's no selected channel, change into a channel we can watch
                    for channel in channels:
                        if (
                            channel.online  # steam online
                            and channel.drops_enabled  # drops are enabled
                            and channel.game == selected_game  # it's a game we've selected
                        ):
                            self.watch(channel)
                            # break the state change chain by clearing the flag
                            self._state_change.clear()
                            break
                    else:
                        self.stop_watching()
                        selected_game = self.gui.games.get_next_selection()
                        if selected_game is None:
                            self.gui.print("No suitable channel to watch.")
                            # TODO: Figure out what to do here.
                            return
                        self.change_state(State.CHANNEL_CLEANUP)
            await self._state_change.wait()

    async def _watch_loop(self, channel: Channel):
        # last_watch is a timestamp of the last time we've sent a watch payload
        # We need this because watch_loop can be cancelled and rescheduled multiple times
        # in quick succession, and apparently Twitch doesn't like that very much
        interval = WATCH_INTERVAL.total_seconds()
        await asyncio.sleep(self._last_watch + interval - time())
        i = 0
        while True:
            await channel.send_watch()
            self._last_watch = time()
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
                    drop_data: JsonType = context["data"]["currentUser"]["dropCurrentSession"]
                    drop_id = drop_data["dropID"]
                    drop = self.get_drop(drop_id)
                    if drop is None:
                        use_active = True
                        logger.error(f"Missing drop: {drop_id}")
                    elif not drop.campaign.active:
                        use_active = True
                    else:
                        drop.update_minutes(drop_data["currentMinutesWatched"])
                        drop.display()
                        with open("log.txt", 'a') as file:
                            debug_log(file, "GQL", drop)
                if use_active:
                    # Sometimes, even GQL fails to give us the correct drop.
                    # In that case, we can use the locally cached inventory to try
                    # and put together the drop that we're actually mining right now
                    selected_game = self.gui.games.get_selection()
                    drop = self.get_active_drop(selected_game)
                    if drop is not None:
                        drop.bump_minutes()
                        drop.display()
                        with open("log.txt", 'a') as file:
                            debug_log(file, "ACT", drop)
                    else:
                        logger.error("Active drop search failed")
            if i == 0:
                # ensure every 30 minutes that we don't have unclaimed points bonus
                await channel.claim_bonus()
            i = (i + 1) % 30
            await asyncio.sleep(self._last_watch + interval - time())

    def watch(self, channel: Channel):
        if self.is_watching(channel):
            # we're already watching the same channel, so there's no point switching
            return
        if self._watching_task is not None:
            self._watching_task.cancel()
        self.gui.channels.set_watching(channel)
        self._watching_channel = channel
        self._watching_task = asyncio.create_task(self._watch_loop(channel))

    def stop_watching(self):
        self.gui.progress.stop_timer()
        self.gui.channels.clear_watching()
        if self._watching_task is not None:
            self._watching_task.cancel()
            self._watching_task = None
        self._watching_channel = None

    def restart_watching(self, channel: Optional[Channel] = None):
        # this forcibly re-sends the watching payload to the specified or currently watched channel
        if channel is None:
            channel = self._watching_channel
        if channel is not None:
            self.stop_watching()
            self._last_watch = time() - 60
            self.watch(channel)

    async def process_stream_state(self, channel_id: int, message: JsonType):
        msg_type = message["type"]
        channel = self.channels.get(channel_id)
        if channel is None:
            logger.error(f"Stream state change for a non-existing channel: {channel_id}")
            return
        if msg_type == "stream-down":
            logger.info(f"{channel.name} goes OFFLINE")
            channel.set_offline()
            if self.is_watching(channel):
                self.gui.print(f"{channel.name} goes OFFLINE, switching...")
                # change the channel if we're currently watching it
                self.change_state(State.CHANNEL_SWITCH)
        elif msg_type == "stream-up":
            logger.info(f"{channel.name} goes ONLINE")
            channel.set_online()
        elif msg_type == "viewcount":
            if not channel.online:
                # if it's not online for some reason, set it so
                channel.set_online()
            else:
                viewers = message["viewers"]
                channel.viewers = viewers
                logger.debug(f"{channel.name} viewers: {viewers}")

    @task_wrapper
    async def process_drops(self, user_id: int, message: JsonType):
        # Message examples:
        # {"type": "drop-progress", data: {"current_progress_min": 3, "required_progress_min": 10}}
        # {"type": "drop-claim", data: {"drop_instance_id": ...}}
        msg_type: str = message["type"]
        if msg_type not in ("drop-progress", "drop-claim"):
            return
        drop_id: str = message["data"]["drop_id"]
        drop: Optional[TimedDrop] = self.get_drop(drop_id)
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
            if mined:
                self.gui.print(
                    f"Claimed drop: {drop.rewards_text()} "
                    f"({campaign.claimed_drops}/{campaign.total_drops})"
                )
            else:
                logger.error(f"Drop claim failed! Drop ID: {drop_id}")
            if not mined or campaign.remaining_drops == 0:
                self.change_state(State.INVENTORY_FETCH)
                return
            # About 4-6s after claiming the drop, next drop can be started
            # by re-sending the watch payload
            await asyncio.sleep(4)
            for attempt in range(6):
                context = await self.gql_request(GQL_OPERATIONS["CurrentDrop"])
                drop_data: JsonType = context["data"]["currentUser"]["dropCurrentSession"]
                with open("log.txt", 'a') as file:
                    print(format(time(), ".6f"), attempt+1, drop_data["dropID"], file=file)
                if drop_data["dropID"] != drop.id:
                    self.restart_watching()
                    break
                await asyncio.sleep(1)
            return
        assert msg_type == "drop-progress"
        if self._drop_update is None:
            # we aren't actually waiting for a progress update right now, so we can just
            # ignore the event this time
            return
        elif drop is not None and drop.campaign.active:
            drop.update_minutes(message["data"]["current_progress_min"])
            drop.display()
            self._drop_update.set_result(True)
            self._drop_update = None  # TODO: remove this together with debug code below
            with open("log.txt", 'a') as file:
                debug_log(file, "WS", drop)
        else:
            # Sometimes, the drop update we receive doesn't actually match what we're mining.
            # This is a Twitch bug workaround: signal the watch loop to use GQL
            # to get the current drop progress.
            self._drop_update.set_result(False)
        self._drop_update = None

    @task_wrapper
    async def process_points(self, user_id: int, message: JsonType):
        # Example payloads:
        # {
        #     "type": "points-earned",
        #     "data": {
        #         "timestamp": "YYYY-MM-DDTHH:MM:SS.123456789Z",
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
        #         "timestamp":"2021-12-23T21:41:35.784041064Z",
        #         "claim": {
        #             "id": "4ae6fefd-3658-40ae-ad3d-92254c576a91",
        #             "user_id": "94275183",
        #             "channel_id": "218893986",
        #             "point_gain": {
        #                 "user_id": "94275183",
        #                 "channel_id": "218893986",
        #                 "total_points": 50,
        #                 "baseline_points": 50,
        #                 "reason_code": "CLAIM",
        #                 "multipliers": []
        #             },
        #             "created_at": "2021-12-23T21:41:31Z"
        #         }
        #     }
        # }
        msg_type = message["type"]
        if msg_type == "points-earned":
            data = message["data"]
            channel = self.channels.get(int(data["channel_id"]))
            points = data["point_gain"]["total_points"]
            balance = data["balance"]["balance"]
            if channel is not None:
                channel.points = balance
                self.gui.channels.display(channel)
            self.gui.print(f"Earned points for watching: {points:3}, total: {balance}")
        elif msg_type == "claim-available":
            claim_data = message["data"]["claim"]
            points = claim_data["point_gain"]["total_points"]
            await self.claim_points(claim_data["channel_id"], claim_data["id"])
            self.gui.print(f"Claimed bonus points: {points}")

    async def _validate_password(self, password: str) -> bool:
        """
        Use Twitch's password validator to validate the password length, characters required, etc.
        Helps avoid running into the CAPTCHA if you mistype your password by mistake.
        Valid length: 8-71
        """
        if not 8 <= len(password) <= 71:
            return False
        payload = {"password": password}
        async with self._session.post(
            f"{AUTH_URL}/api/v1/password_strength", json=payload
        ) as response:
            strength_response = await response.json()
        return strength_response["isValid"]

    async def ask_login(self) -> LoginData:
        while True:
            data = await self.gui.login.ask_login()
            if await self._validate_password(data.password):
                return data

    async def _login(self) -> str:
        logger.debug("Login flow started")

        payload: JsonType = {
            "client_id": CLIENT_ID,
            "undelete_user": False,
            "remember_me": True,
        }

        while True:
            username, password, token = await self.ask_login()
            payload["username"] = username
            payload["password"] = password
            # remove stale 2FA tokens, if present
            payload.pop("authy_token", None)
            payload.pop("twitchguard_code", None)
            for attempt in range(2):
                async with self._session.post(f"{AUTH_URL}/login", json=payload) as response:
                    login_response: JsonType = await response.json()

                # Feed this back in to avoid running into CAPTCHA if possible
                if "captcha_proof" in login_response:
                    payload["captcha"] = {"proof": login_response["captcha_proof"]}

                # Error handling
                if "error_code" in login_response:
                    error_code: int = login_response["error_code"]
                    logger.debug(f"Login error code: {error_code}")
                    if error_code == 1000:
                        # we've failed bois
                        logger.debug("Login failed due to CAPTCHA")
                        raise CaptchaRequired()
                    elif error_code == 3001:
                        # wrong password you dummy
                        logger.debug("Login failed due to incorrect login or pass")
                        self.gui.print("Incorrect username or password.")
                        self.gui.login.clear(password=True)
                        break
                    elif error_code in (
                        3012,  # Invalid authy token
                        3023,  # Invalid email code
                    ):
                        logger.debug("Login failed due to incorrect 2FA code")
                        if error_code == 3023:
                            self.gui.print("Incorrect email code.")
                        else:
                            self.gui.print("Incorrect 2FA code.")
                        self.gui.login.clear(token=True)
                        break
                    elif error_code in (
                        3011,  # Authy token needed
                        3022,  # Email code needed
                    ):
                        # 2FA handling
                        logger.debug("2FA token required")
                        email = error_code == 3022
                        if not token:
                            # user didn't provide a token, so ask them for it
                            if email:
                                self.gui.print("Email code required. Check your email.")
                            else:
                                self.gui.print("2FA token required.")
                            break
                        if email:
                            payload["twitchguard_code"] = token
                        else:
                            payload["authy_token"] = token
                        continue
                    else:
                        raise LoginException(login_response["error"])
                # Success handling
                if "access_token" in login_response:
                    # we're in bois
                    self._access_token = cast(str, login_response["access_token"])
                    logger.debug("Access token granted")
                    self.gui.login.clear()
                    return self._access_token

    async def check_login(self) -> None:
        if self._access_token is not None and self._user_id is not None:
            # we're all good
            return
        # looks like we're missing something
        logger.debug("Checking login")
        self.gui.login.update("Logging in...", None)
        jar = cast(aiohttp.CookieJar, self._session.cookie_jar)
        for attempt in range(2):
            cookie = jar.filter_cookies("https://twitch.tv")  # type: ignore
            if not cookie:
                # no cookie - login
                await self._login()
                # store our auth token inside the cookie
                cookie["auth-token"] = cast(str, self._access_token)
            elif self._access_token is None:
                # have cookie - get our access token
                self._access_token = cookie["auth-token"].value
                logger.debug("Restoring session from cookie")
            # validate our access token, by obtaining user_id
            async with self._session.get(
                "https://id.twitch.tv/oauth2/validate",
                headers={"Authorization": f"OAuth {self._access_token}"}
            ) as response:
                status = response.status
                if status == 401:
                    # the access token we have is invalid - clear the cookie and reauth
                    logger.debug("Restored session is invalid")
                    jar.clear_domain("twitch.tv")
                    continue
                elif status == 200:
                    validate_response = await response.json()
                    break
        else:
            raise RuntimeError("Login verification failure")
        self._user_id = int(validate_response["user_id"])
        cookie["persistent"] = str(self._user_id)
        self._is_logged_in.set()
        logger.debug(f"Login successful, user ID: {self._user_id}")
        self.gui.login.update("Logged in", self._user_id)
        # update our cookie and save it
        jar.update_cookies(cookie, URL("https://twitch.tv"))
        jar.save(COOKIES_PATH)

    async def gql_request(self, op: GQLOperation) -> JsonType:
        await self.check_login()
        headers = {
            "Authorization": f"OAuth {self._access_token}",
            "Client-Id": CLIENT_ID,
        }
        gql_logger.debug(f"GQL Request: {op}")
        async with self._session.post(GQL_URL, json=op, headers=headers) as response:
            response_json = await response.json()
            gql_logger.debug(f"GQL Response: {response_json}")
            return response_json

    async def fetch_inventory(self) -> None:
        response = await self.gql_request(GQL_OPERATIONS["Inventory"])
        inventory = response["data"]["currentUser"]["inventory"]
        self.inventory = [
            DropsCampaign(self, data) for data in inventory["dropCampaignsInProgress"]
        ]
        context = await self.gql_request(GQL_OPERATIONS["CurrentDrop"])
        drop_data = context["data"]["currentUser"]["dropCurrentSession"]
        with open("log.txt", 'a') as file:
            if drop_data is None:
                print(time(), None, sep='\t', file=file, flush=True)
            else:
                print(
                    time(), drop_data.get("currentMinutesWatched"), sep='\t', file=file, flush=True
                )

    def get_drop(self, drop_id: str) -> Optional[TimedDrop]:
        for campaign in self.inventory:
            drop = campaign.get_drop(drop_id)
            if drop is not None:
                return drop
        return None

    def get_active_drop(self, game: Game) -> Optional[TimedDrop]:
        drops = sorted(
            (
                drop
                for campaign in self.inventory
                if campaign.active and campaign.game == game
                for drop in campaign.timed_drops.values()
                if drop.can_earn
            ),
            key=lambda d: d.remaining_minutes,
        )
        if drops:
            return drops[0]
        return None

    async def get_live_streams(self, game: Game, tag_ids: List[str]) -> List[Channel]:
        limit = 45
        response = await self.gql_request(
            GQL_OPERATIONS["GameDirectory"].with_variables({
                "limit": limit,
                "name": game.name,
                "options": {
                    "includeRestricted": ["SUB_ONLY_LIVE"],
                    "tags": tag_ids,
                },
            })
        )
        return [
            Channel.from_directory(self, stream_channel_data["node"])
            for stream_channel_data in response["data"]["game"]["streams"]["edges"]
        ]

    async def claim_points(self, channel_id: Union[str, int], claim_id: str) -> None:
        variables = {"input": {"channelID": str(channel_id), "claimID": claim_id}}
        await self.gql_request(
            GQL_OPERATIONS["ClaimCommunityPoints"].with_variables(variables)
        )
