from __future__ import annotations

import os
import asyncio
import logging
from yarl import URL
from getpass import getpass
from functools import partial
from typing import Any, Optional, Union, List, Dict, Collection, cast

try:
    import aiohttp
except ImportError:
    raise ImportError("You have to run 'python -m pip install aiohttp' first")

from channel import Channel
from websocket import Websocket
from inventory import DropsCampaign, Game
from exceptions import LoginException, CaptchaRequired
from constants import (
    CLIENT_ID,
    USER_AGENT,
    COOKIES_PATH,
    AUTH_URL,
    GQL_URL,
    GQL_OPERATIONS,
    DROPS_ENABLED_TAG,
    GQLOperation,
    WebsocketTopic,
    get_topic,
)


logger = logging.getLogger("TwitchDrops")


class Twitch:
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.username: Optional[str] = username
        self.password: Optional[str] = password
        # Cookies, session and auth
        cookie_jar = aiohttp.CookieJar()
        if os.path.isfile(COOKIES_PATH):
            cookie_jar.load(COOKIES_PATH)
        self._session = aiohttp.ClientSession(
            cookie_jar=cookie_jar, headers={"User-Agent": USER_AGENT}, loop=loop
        )
        self._access_token: Optional[str] = None
        self._user_id: Optional[int] = None
        self._is_logged_in = asyncio.Event()
        # Websocket
        self.websocket = Websocket(self)
        # Storing, watching and changing channels
        self.channels: Dict[int, Channel] = {}
        self._watching_channel: Optional[Channel] = None
        self._watching_task: Optional[asyncio.Task[Any]] = None
        self._channel_change = asyncio.Event()
        # Inventory
        self.inventory: List[DropsCampaign] = []

    def wait_until_login(self):
        return self._is_logged_in.wait()

    async def close(self):
        print("Exiting...")
        self._session.cookie_jar.save(COOKIES_PATH)  # type: ignore
        self.stop_watching()
        await self._session.close()
        await self.websocket.close()
        await asyncio.sleep(1)  # allows aiohttp to safely close the session

    def is_currently_watching(self, channel: Channel) -> bool:
        return self._watching_channel is not None and self._watching_channel == channel

    async def run(self, channel_names: Optional[List[str]] = None):
        """
        Main method that runs the whole client.

        Here, we manage several things, specifically:
        • Fetching the drops inventory to make sure that everything we can claim, is claimed
        • Selecting a stream to watch, and watching it
        • Changing the stream that's being watched if necessary
        """
        # Start our websocket connection - shouldn't require task tracking
        asyncio.create_task(self.websocket.connect())
        # Claim the drops we can
        self.inventory = await self.get_inventory()
        games = set()
        for campaign in self.inventory:
            if campaign.status == "UPCOMING":
                # we have no use in processing upcoming campaigns here
                continue
            for drop in campaign.timed_drops.values():
                if drop.can_earn:
                    games.add(campaign.game)
                if drop.can_claim:
                    await drop.claim()
        # games now has all games we want to farm drops for
        if not channel_names:
            # get a list of all channels with drops enabled
            print("Fetching suitable live channels to watch...")
            live_streams: Dict[Game, List[Channel]] = await self.get_live_streams(
                games, [DROPS_ENABLED_TAG]
            )
            for game, channels in live_streams.items():
                for channel in channels:
                    self.channels[channel.id] = channel
                    print(f"Added channel: {channel.name} for game: {game.name}")
        else:
            # Fetch information about all channels we're supposed to handle
            for channel_name in channel_names:
                channel: Channel = await Channel(self, channel_name)  # type: ignore
                self.channels[channel.id] = channel
        # Sub to these channel updates
        topics: List[WebsocketTopic] = []
        for channel_id in self.channels:
            topics.append(
                get_topic(
                    "VideoPlayback", channel_id, partial(self.process_stream_state, channel_id)
                )
            )
        await self.websocket.add_topics(topics)

        # Repeat: Change into a channel we can watch, then reset the flag
        self._channel_change.set()
        refresh_channels = False  # we're entering having fresh channel data already
        while True:
            # wait for the change channel signal
            await self._channel_change.wait()
            for channel in self.channels.values():
                if (
                    channel.stream is not None  # steam online
                    and channel.stream.drops_enabled  # drops are enabled
                    and channel.stream.game in games  # streams a game we can earn drops in
                ):
                    self.watch(channel)
                    refresh_channels = True
                    self._channel_change.clear()
                    break
            else:
                # there's no available channel to watch
                if refresh_channels:
                    # refresh the status of all channels,
                    # to make sure that our websocket didn't miss anything til this point
                    print("No suitable channel to watch, refreshing...")
                    for channel in self.channels.values():
                        await channel.get_stream()
                        await asyncio.sleep(0.5)
                    refresh_channels = False
                    continue
                print("No suitable channel to watch, retrying in 120 seconds")
                await asyncio.sleep(120)

    def watch(self, channel: Channel):
        if self._watching_task is not None:
            self._watching_task.cancel()

        async def watcher(channel: Channel):
            op = GQL_OPERATIONS["ChannelPointsContext"].with_variables(
                {"channelLogin": channel.name}
            )
            i = 0
            while True:
                await channel._send_watch()
                if i == 0:
                    # ensure every 30 minutes that we don't have unclaimed points bonus
                    response = await self.gql_request(op)
                    channel_data: Dict[str, Any] = response["data"]["community"]["channel"]
                    claim_available: Dict[str, Any] = (
                        channel_data["self"]["communityPoints"]["availableClaim"]
                    )
                    if claim_available:
                        await self.claim_points(channel_data["id"], claim_available["id"])
                        logger.info("Claimed bonus points")
                i = (i + 1) % 30
                await asyncio.sleep(59)

        game = channel.stream.game.name if channel.stream is not None else "<Unknown>"
        print(f"Watching: {channel.name}, game: {game}")
        self._watching_channel = channel
        self._watching_task = asyncio.create_task(watcher(channel))

    def stop_watching(self):
        if self._watching_task is not None:
            logger.warning("Watching stopped.")
            self._watching_task.cancel()
            self._watching_task = None
        self._watching_channel = None

    async def process_stream_state(self, channel_id: int, message: Dict[str, Any]):
        msg_type = message["type"]
        channel = self.channels.get(channel_id)
        if channel is None:
            logger.error(f"Stream state change for a non-existing channel: {channel_id}")
            return
        if msg_type == "stream-down":
            logger.info(f"{channel.name} goes OFFLINE")
            channel.set_offline()
            if self.is_currently_watching(channel):
                # change the channel if we're currently watching it
                self._channel_change.set()
        elif msg_type == "stream-up":
            logger.info(f"{channel.name} goes ONLINE")
            channel.set_online()
        elif msg_type == "viewcount":
            if not channel.online:
                # if it's not online for some reason, set it so
                channel.set_online()
            else:
                assert channel.stream is not None
                viewers = message["viewers"]
                channel.stream.viewer_count = viewers
                logger.info(f"{channel.name} viewers: {viewers}")

    async def _validate_password(self, password: str) -> bool:
        """
        Use Twitch's password validator to validate the password length, characters required, etc.
        Helps avoid running into the CAPTCHA if you mistype your password by mistake.
        """
        payload = {"password": password}
        async with self._session.post(
            f"{AUTH_URL}/api/v1/password_strength", json=payload
        ) as response:
            strength_response = await response.json()
        return strength_response["isValid"]

    async def get_password(self) -> str:
        """
        A simple loop that'll keep asking for password, until it's considered valid.
        """
        while True:
            password = getpass()
            if await self._validate_password(password):
                return password

    async def _login(self) -> str:
        logger.debug("Login flow started")
        if self.username is None:
            self.username = input("Username: ")
        if self.password is None:
            print(
                "\nReminder: Passwords can be pasted in by pressing right click a single time\n"
                "inside the window. Due to security reasons, no feedback is displayed.\n"
                "Make sure not to paste it in twice.\n"
            )
            self.password = await self.get_password()

        payload: Dict[str, Any] = {
            "username": self.username,
            "password": self.password,
            "client_id": CLIENT_ID,
            "undelete_user": False,
            "remember_me": True,
        }

        for attempt in range(10):
            async with self._session.post(f"{AUTH_URL}/login", json=payload) as response:
                login_response = await response.json()

            # Feed this back in to avoid running into CAPTCHA if possible
            if "captcha_proof" in login_response:
                payload["captcha"] = {"proof": login_response["captcha_proof"]}

            # Error handling
            if "error_code" in login_response:
                error_code = login_response["error_code"]
                logger.debug(f"Login error code: {error_code}")
                if error_code == 1000:
                    # we've failed bois
                    logger.debug("Login failed due to CAPTCHA")
                    raise CaptchaRequired()
                elif error_code == 3001:
                    # wrong password you dummy
                    logger.debug("Login failed due to incorrect login or pass")
                    print(f"Incorrect username or password.\nUsername: {self.username}")
                    self.password = await self.get_password()
                elif error_code in (
                    3011,  # Authy token needed
                    3012,  # Invalid authy token
                    3022,  # Email code needed
                    3023,  # Invalid email code
                ):
                    # 2FA handling
                    email = error_code in (3022, 3023)
                    logger.debug("2FA token required")
                    token = input("2FA token: ")
                    if email:
                        # email code
                        payload["twitchguard_code"] = token
                    else:
                        # authy token
                        payload["authy_token"] = token
                    continue
                else:
                    raise LoginException(login_response["error"])

            # Success handling
            if "access_token" in login_response:
                # we're in bois
                self._access_token = login_response["access_token"]
                logger.debug(f"Access token: {self._access_token}")
                break

        if self._access_token is None:
            # this means we've ran out of retries
            raise LoginException("Ran out of login retries")
        return self._access_token

    async def check_login(self) -> None:
        if self._access_token is not None and self._user_id is not None:
            # we're all good
            return
        # looks like we're missing something
        print("Logging in")
        jar = cast(aiohttp.CookieJar, self._session.cookie_jar)
        while True:
            cookie = jar.filter_cookies("https://twitch.tv")  # type: ignore
            if not cookie:
                # no cookie - login
                await self._login()
                # store our auth token inside the cookie
                cookie["auth-token"] = cast(str, self._access_token)
            elif self._access_token is None:
                # have cookie - get our access token
                self._access_token = cookie["auth-token"].value
                logger.debug("Session restored from cookie")
            # validate our access token, by obtaining user_id
            async with self._session.get(
                "https://id.twitch.tv/oauth2/validate",
                headers={"Authorization": f"OAuth {self._access_token}"}
            ) as response:
                status = response.status
                if status == 401:
                    # the access token we have is invalid - clear the cookie and reauth
                    jar.clear_domain("twitch.tv")
                    continue
                elif status == 200:
                    validate_response = await response.json()
                    break
        self._user_id = cookie["persistent"] = validate_response["user_id"]
        self._is_logged_in.set()
        print(f"Login successful, User ID: {self._user_id}")
        # update our cookie and save it
        jar.update_cookies(cookie, URL("https://twitch.tv"))
        jar.save(COOKIES_PATH)

    async def gql_request(self, op: GQLOperation) -> Dict[str, Any]:
        await self.check_login()
        headers = {
            "Authorization": f"OAuth {self._access_token}",
            "Client-Id": CLIENT_ID,
        }
        logger.debug(f"GQL Request: {op}")
        async with self._session.post(GQL_URL, json=op, headers=headers) as response:
            response_json = await response.json()
            logger.debug(f"GQL Response: {response_json}")
            return response_json

    async def get_inventory(self) -> List[DropsCampaign]:
        response = await self.gql_request(GQL_OPERATIONS["Inventory"])
        inventory = response["data"]["currentUser"]["inventory"]
        return [DropsCampaign(self, data) for data in inventory["dropCampaignsInProgress"]]

    async def get_live_streams(
        self, games: Collection[Game], tag_ids: List[str]
    ) -> Dict[Game, List[Channel]]:
        limit = int(45 / len(games))
        live_streams = {}
        for game in games:
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
            live_streams[game] = [
                await Channel.from_directory(self, stream_channel_data["node"])
                for stream_channel_data in response["data"]["game"]["streams"]["edges"]
            ]
        return live_streams

    async def claim_points(self, channel_id: Union[str, int], claim_id: str):
        variables = {"input": {"channelID": str(channel_id), "claimID": claim_id}}
        await self.gql_request(
            GQL_OPERATIONS["ClaimCommunityPoints"].with_variables(variables)
        )
