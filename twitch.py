from __future__ import annotations

import os
import asyncio
import logging
from yarl import URL
from time import time
from itertools import chain
from datetime import datetime
from functools import partial
from contextlib import suppress
from typing import (
    Optional, Union, List, Dict, Set, OrderedDict, Callable, Iterable, cast, TYPE_CHECKING
)

try:
    import aiohttp
except ModuleNotFoundError as exc:
    raise ImportError("You have to run 'pip install aiohttp' first") from exc

from channel import Channel
from websocket import WebsocketPool
from gui import LoginData, GUIManager
from inventory import DropsCampaign, TimedDrop
from exceptions import LoginException, CaptchaRequired
from utils import task_wrapper, timestamp, Game, AwaitableValue, OrderedSet
from constants import (
    GQL_URL,
    AUTH_URL,
    CLIENT_ID,
    USER_AGENT,
    COOKIES_PATH,
    GQL_OPERATIONS,
    WATCH_INTERVAL,
    DROPS_ENABLED_TAG,
    JsonType,
    State,
    GQLOperation,
    WebsocketTopic,
)

if TYPE_CHECKING:
    from main import ParsedArgs


logger = logging.getLogger("TwitchDrops")
gql_logger = logging.getLogger("TwitchDrops.gql")


class Twitch:
    def __init__(self, options: ParsedArgs):
        self.options = options
        # State management
        self._state: State = State.INVENTORY_FETCH
        self._state_change = asyncio.Event()
        self.game: Optional[Game] = None
        self.inventory: Dict[Game, List[DropsCampaign]] = {}
        # GUI
        self.gui = GUIManager(self)
        # Cookies, session and auth
        self._session: Optional[aiohttp.ClientSession] = None
        self._access_token: Optional[str] = None
        self._user_id: Optional[int] = None
        self._is_logged_in = asyncio.Event()
        # Storing and watching channels
        self.channels: OrderedDict[int, Channel] = OrderedDict()
        self.watching_channel: AwaitableValue[Channel] = AwaitableValue()
        self._watching_task: Optional[asyncio.Task[None]] = None
        self._watching_restart = asyncio.Event()
        self._drop_update: Optional[asyncio.Future[bool]] = None
        # Websocket
        self.websocket = WebsocketPool(self)

    async def initialize(self) -> None:
        cookie_jar = aiohttp.CookieJar()
        if os.path.isfile(COOKIES_PATH):
            cookie_jar.load(COOKIES_PATH)
        self._session = aiohttp.ClientSession(
            cookie_jar=cookie_jar,
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(connect=5, total=10),
        )

    async def shutdown(self) -> None:
        start_time = time()
        self.gui.print("Exiting...")
        self.stop_watching()
        if self._watching_task is not None:
            self._watching_task.cancel()
            self._watching_task = None
        # close session and stop websocket
        if self._session is not None:
            self._session.cookie_jar.save(COOKIES_PATH)  # type: ignore
            await self._session.close()
            self._session = None
        await self.websocket.stop()
        # wait at least one full second + whatever it takes to complete the closing
        # this allows aiohttp to safely close the session
        await asyncio.sleep(start_time + 1 - time())

    def wait_until_login(self):
        return self._is_logged_in.wait()

    def change_state(self, state: State) -> None:
        if self._state is not State.EXIT:
            # prevent state changing once we switch to exit state
            self._state = state
        self._state_change.set()

    def state_change(self, state: State) -> Callable[[], None]:
        # this is identical to change_state, but defers the call
        # perfect for GUI usage
        return partial(self.change_state, state)

    def close(self):
        """
        Called when the application is requested to close by the operating system,
        usually by receiving a SIGINT or SIGTERM.
        """
        self.gui.close()

    def request_close(self):
        """
        Called when the application is requested to close by the user,
        usually by the console or application window being closed.
        """
        self.change_state(State.EXIT)

    def prevent_close(self):
        """
        Called when the application window has to be prevented from closing, even after the user
        closes it with X. Usually used solely to display tracebacks drom the closing sequence.
        """
        self.gui.prevent_close()

    def print(self, *args, **kwargs):
        """
        Can be used to print messages within the GUI.
        """
        self.gui.print(*args, **kwargs)

    def is_watching(self, channel: Channel) -> bool:
        watching_channel = self.watching_channel.get_with_default(None)
        return watching_channel is not None and watching_channel == channel

    async def run(self):
        """
        Main method that runs the whole client.

        Here, we manage several things, specifically:
        • Fetching the drops inventory to make sure that everything we can claim, is claimed
        • Selecting a stream to watch, and watching it
        • Changing the stream that's being watched if necessary
        """
        if self._session is None:
            await self.initialize()
        self.gui.start()
        if self._watching_task is not None:
            self._watching_task.cancel()
        self._watching_task = asyncio.create_task(self._watch_loop())
        await self.check_login()
        # Add default topics
        assert self._user_id is not None
        self.websocket.add_topics([
            WebsocketTopic("User", "Drops", self._user_id, self.process_drops),
            WebsocketTopic("User", "CommunityPoints", self._user_id, self.process_points),
        ])
        games: List[Game] = []
        self.change_state(State.INVENTORY_FETCH)
        while True:
            if self._state is State.IDLE:
                # clear the flag and wait until it's set again
                self._state_change.clear()
            elif self._state is State.INVENTORY_FETCH:
                await self.fetch_inventory()
                self.change_state(State.GAMES_UPDATE)
            elif self._state is State.GAMES_UPDATE:
                # Figure out which games to watch, and claim the drops we can
                games.clear()
                for game, campaigns in self.inventory.items():
                    add_game = False
                    for campaign in campaigns:
                        if not campaign.upcoming:
                            # claim drops from expired and active campaigns
                            active = campaign.active
                            for drop in campaign.drops:
                                if drop.can_claim:
                                    await drop.claim()
                                # add game only for active campaigns
                                if active and not add_game and drop.can_earn():
                                    add_game = True
                    if add_game:
                        games.append(game)
                self.change_state(State.GAME_SELECT)
            elif self._state is State.GAME_SELECT:
                # 'games' has all games we can mine drops for
                # if it's empty, there's no point in continuing
                if not games:
                    self.gui.print("No active campaigns to mine drops for.")
                    return
                # only start the websocket after we confirm there are drops to mine
                await self.websocket.start()
                self.gui.games.set_games(games)
                self.game = self.gui.games.get_selection()
                # pre-display the active drop without a countdown
                active_drop = self.get_active_drop()
                if active_drop is not None:
                    active_drop.display(countdown=False)
                self.restart_watching()
                self.change_state(State.CHANNELS_CLEANUP)
            elif self._state is State.CHANNELS_CLEANUP:
                if self.game is None:
                    # remove everything
                    to_remove: List[Channel] = list(self.channels.values())
                else:
                    # remove all channels that:
                    to_remove = [
                        channel
                        for channel in self.channels.values()
                        if channel.offline  # are offline
                        or not channel.priority  # aren't prioritized
                        # aren't streaming the game we want anymore
                        or channel.game is None or channel.game != self.game
                    ]
                self.websocket.remove_topics(
                    WebsocketTopic.as_str("Channel", "VideoPlayback", channel.id)
                    for channel in to_remove
                )
                watching_channel = self.watching_channel.get_with_default(None)
                if watching_channel is not None and watching_channel in to_remove:
                    # we're removing a channel we're watching
                    self.stop_watching()
                for channel in to_remove:
                    del self.channels[channel.id]
                    channel.remove()
                self.gui.channels.shrink()
                self.change_state(State.CHANNELS_FETCH)
            elif self._state is State.CHANNELS_FETCH:
                if self.game is None:
                    self.change_state(State.GAME_SELECT)
                else:
                    # pre-display the active drop without substracting a minute
                    active_drop = self.get_active_drop()
                    if active_drop is not None:
                        active_drop.display(countdown=False)
                    # gather ACLs from campaigns
                    no_acl = False
                    new_channels: OrderedSet[Channel] = OrderedSet()
                    for campaign in self.inventory[self.game]:
                        acls = campaign.allowed_channels
                        if acls:
                            for channel in acls:
                                new_channels.add(channel)
                        else:
                            no_acl = True
                    # set them online if possible
                    await asyncio.gather(*(channel.check_online() for channel in new_channels))
                    if no_acl:
                        # if there's at least one game without an ACL,
                        # get a list of all live channels with drops enabled
                        live_streams: List[Channel] = await self.get_live_streams()
                        for channel in live_streams:
                            new_channels.add(channel)
                    if any(self.can_watch(channel) for channel in new_channels):
                        # there are streams we can watch, so let's pre-display the active drop
                        # again, but this time with a substracted minute
                        active_drop = self.get_active_drop()
                        if active_drop is not None:
                            active_drop.display(countdown=False, subone=True)
                    # add them, filtering out ones we already have
                    for channel in new_channels:
                        channel_id = channel.id
                        if channel_id not in self.channels:
                            self.channels[channel_id] = channel
                            channel.display()
                    # Subscribe to these channel's state updates
                    topics: List[WebsocketTopic] = [
                        WebsocketTopic(
                            "Channel", "VideoPlayback", channel_id, self.process_stream_state
                        )
                        for channel_id in self.channels
                    ]
                    self.websocket.add_topics(topics)
                    self.change_state(State.CHANNEL_SWITCH)
            elif self._state is State.CHANNEL_SWITCH:
                if self.game is None:
                    self.change_state(State.GAME_SELECT)
                else:
                    # Change into the selected channel, stay in the watching channel,
                    # or select a new channel that meets the required conditions
                    channels: Iterable[Channel]
                    priority_channels: List[Channel] = []
                    selected_channel = self.gui.channels.get_selection()
                    if selected_channel is not None:
                        self.gui.channels.clear_selection()
                        priority_channels.append(selected_channel)
                    watching_channel = self.watching_channel.get_with_default(None)
                    if watching_channel is not None:
                        priority_channels.append(watching_channel)
                    channels = chain(priority_channels, self.channels.values())
                    # If there's no selected channel, change into a channel we can watch
                    for channel in channels:
                        if self.can_watch(channel):
                            self.watch(channel)
                            # break the state change chain by clearing the flag
                            self._state_change.clear()
                            break
                    else:
                        self.stop_watching()
                        self.gui.print(f"No suitable channel to watch for game: {self.game}")
                        self.change_state(State.IDLE)
            elif self._state is State.EXIT:
                # we've been requested to exit the application
                break
            await self._state_change.wait()

    async def _watch_sleep(self, delay: float) -> None:
        # we use wait_for here to allow an asyncio.sleep that can be ended prematurely,
        # without cancelling the containing task
        self._watching_restart.clear()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._watching_restart.wait(), timeout=delay)

    @task_wrapper
    async def _watch_loop(self) -> None:
        interval = WATCH_INTERVAL.total_seconds()
        i = 1
        while True:
            channel = await self.watching_channel.get()
            succeeded = await channel.send_watch()
            if not succeeded:
                # this usually means there are connection problems
                self.gui.print("Connection problems, retrying in 60 seconds...")
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
                    drop_data: JsonType = context["data"]["currentUser"]["dropCurrentSession"]
                    drop_id = drop_data["dropID"]
                    drop = self.get_drop(drop_id)
                    if drop is None:
                        use_active = True
                        logger.error(f"Missing drop: {drop_id}")
                    elif not drop.can_earn(channel):
                        use_active = True
                    else:
                        drop.update_minutes(drop_data["currentMinutesWatched"])
                        drop.display()
                if use_active:
                    # Sometimes, even GQL fails to give us the correct drop.
                    # In that case, we can use the locally cached inventory to try
                    # and put together the drop that we're actually mining right now
                    drop = self.get_active_drop()
                    if drop is not None:
                        drop.bump_minutes()
                        drop.display()
                    else:
                        logger.error("Active drop search failed")
            if i % 30 == 1:
                # ensure every 30 minutes that we don't have unclaimed points bonus
                await channel.claim_bonus()
            if i % 60 == 0:
                # cleanup channels every hour
                self.change_state(State.CHANNELS_CLEANUP)
            i = (i + 1) % 3600
            await self._watch_sleep(last_watch + interval - time())

    def can_watch(self, channel: Channel) -> bool:
        if self.game is None:
            return False
        return (
            channel.online  # steam online
            and channel.drops_enabled  # drops are enabled
            and channel.game == self.game  # it's a game we've selected
            # we can progress any campaign for the selected game
            and any(
                drop.can_earn(channel)
                for campaign in self.inventory[self.game]
                for drop in campaign.drops
            )
        )

    def watch(self, channel: Channel):
        if self.is_watching(channel):
            # we're already watching the same channel, so there's no point switching
            return
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
        if msg_type == "stream-down":
            channel.set_offline()
        elif msg_type == "stream-up":
            channel.set_online()
        elif msg_type == "viewcount":
            if not channel.online:
                # if it's not online for some reason, set it so
                channel.set_online()
            else:
                viewers = message["viewers"]
                channel.viewers = viewers
                # logger.debug(f"{channel.name} viewers: {viewers}")

    def on_online(self, channel: Channel):
        """
        Called by a Channel when it goes online (after pending).
        """
        logger.debug(f"{channel.name} goes ONLINE")
        if channel.priority:
            wch = self.watching_channel.get_with_default(None)
            if wch is not None and not wch.priority and self.can_watch(channel):
                self.watch(channel)

    def on_offline(self, channel: Channel):
        """
        Called by a Channel when it goes offline.
        """
        # change the channel if we're currently watching it
        if self.is_watching(channel):
            self.gui.print(f"{channel.name} goes OFFLINE, switching...")
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
                claim_text = (
                    f"{drop.rewards_text()} "
                    f"({campaign.claimed_drops}/{campaign.total_drops})"
                )
                self.gui.print(f"Claimed drop: {claim_text}")
                self.gui.tray.notify(claim_text, "Mined Drop")
            else:
                logger.error(f"Drop claim failed! Drop ID: {drop_id}")
            if not mined or campaign.remaining_drops == 0:
                self.change_state(State.GAMES_UPDATE)
                return
            # About 4-20s after claiming the drop, next drop can be started
            # by re-sending the watch payload. We can test for it by fetching the current drop
            # via GQL, and then comparing drop IDs.
            await asyncio.sleep(4)
            for attempt in range(8):
                context = await self.gql_request(GQL_OPERATIONS["CurrentDrop"])
                drop_data: JsonType = context["data"]["currentUser"]["dropCurrentSession"]
                if drop_data["dropID"] != drop.id:
                    self.restart_watching()
                    break
                await asyncio.sleep(2)
            return
        assert msg_type == "drop-progress"
        watching_channel = self.watching_channel.get_with_default(None)
        if self._drop_update is None:
            # we aren't actually waiting for a progress update right now, so we can just
            # ignore the event this time
            return
        elif drop is not None and drop.can_earn(watching_channel):
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
        assert self._session is not None
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
        assert self._session is not None

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
                        logger.debug("Login failed due to incorrect username or password")
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
        assert self._session is not None
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
        assert self._session is not None
        headers = {
            "Authorization": f"OAuth {self._access_token}",
            "Client-Id": CLIENT_ID,
        }
        gql_logger.debug(f"GQL Request: {op}")
        for attempt in range(5):
            try:
                async with self._session.post(GQL_URL, json=op, headers=headers) as response:
                    response_json = await response.json()
                    gql_logger.debug(f"GQL Response: {response_json}")
                    return response_json
            except (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError):
                continue
        raise RuntimeError(f"Ran out of attempts while handling a GQL request: {op}")

    async def fetch_campaign(
        self, campaign_id: str, claimed_benefits: Dict[str, datetime]
    ) -> DropsCampaign:
        response = await self.gql_request(
            GQL_OPERATIONS["CampaignDetails"].with_variables(
                {"channelLogin": str(self._user_id), "dropID": campaign_id}
            )
        )
        return DropsCampaign(self, response["data"]["user"]["dropCampaign"], claimed_benefits)

    async def fetch_inventory(self) -> None:
        # fetch all available campaign IDs, that are currently ACTIVE and account is connected
        response = await self.gql_request(GQL_OPERATIONS["Campaigns"])
        data = response["data"]["currentUser"]["dropCampaigns"] or []
        applicable_statuses = ("ACTIVE", "UPCOMING")
        available_campaigns: Set[str] = set(
            c["id"] for c in data
            if c["status"] in applicable_statuses and c["self"]["isAccountConnected"]
        )
        # fetch in-progress campaigns (inventory)
        response = await self.gql_request(GQL_OPERATIONS["Inventory"])
        inventory = response["data"]["currentUser"]["inventory"]
        ongoing_campaigns = inventory["dropCampaignsInProgress"] or []
        # this contains claimed benefit edge IDs, not drop IDs
        claimed_benefits: Dict[str, datetime] = {
            b["id"]: timestamp(b["lastAwardedAt"]) for b in inventory["gameEventDrops"]
        }
        campaigns: List[DropsCampaign] = [
            DropsCampaign(self, campaign_data, claimed_benefits)
            for campaign_data in ongoing_campaigns
        ]
        # filter out in-progress campaigns from all available campaigns,
        # since we already have all information needed for them
        for campaign in campaigns:
            available_campaigns.discard(campaign.id)
        # add campaigns that remained, that can be earned but are not in-progress yet
        for campaign_id in available_campaigns:
            campaign = await self.fetch_campaign(campaign_id, claimed_benefits)
            if any(drop.can_earn() for drop in campaign.drops):
                campaigns.append(campaign)
        campaigns.sort(key=lambda c: c.ends_at)
        self.inventory.clear()
        for campaign in campaigns:
            game = campaign.game
            if game not in self.inventory:
                self.inventory[game] = []
            self.inventory[game].append(campaign)

    def get_drop(self, drop_id: str) -> Optional[TimedDrop]:
        """
        Returns a drop from the inventory, based on it's ID.
        """
        # try it with the currently selected game first
        if self.game is not None:
            for campaign in self.inventory[self.game]:
                drop = campaign.timed_drops.get(drop_id)
                if drop is not None:
                    return drop
        # fallback to checking all campaigns
        for campaign in chain(*self.inventory.values()):
            drop = campaign.timed_drops.get(drop_id)
            if drop is not None:
                return drop
        return None

    def get_active_drop(self) -> Optional[TimedDrop]:
        if self.game is None:
            return None
        watching_channel = self.watching_channel.get_with_default(None)
        drops = sorted(
            (
                drop
                for campaign in self.inventory[self.game]
                if campaign.active
                for drop in campaign.drops
                if drop.can_earn(watching_channel)
            ),
            key=lambda d: d.remaining_minutes,
        )
        if drops:
            return drops[0]
        return None

    async def get_live_streams(self) -> List[Channel]:
        if self.game is None:
            return []
        limit = 30
        response = await self.gql_request(
            GQL_OPERATIONS["GameDirectory"].with_variables({
                "limit": limit,
                "name": self.game.name,
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

    async def claim_points(self, channel_id: Union[str, int], claim_id: str) -> None:
        await self.gql_request(
            GQL_OPERATIONS["ClaimCommunityPoints"].with_variables(
                {"input": {"channelID": str(channel_id), "claimID": claim_id}}
            )
        )
