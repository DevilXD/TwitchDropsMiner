from __future__ import annotations

import os
import asyncio
import logging
from yarl import URL
from time import time
from itertools import chain
from functools import partial
from typing import TYPE_CHECKING
from collections import OrderedDict
from contextlib import suppress, asynccontextmanager

try:
    import aiohttp
except ModuleNotFoundError as exc:
    raise ImportError("You have to run 'pip install aiohttp' first") from exc

from gui import GUIManager
from channel import Channel
from websocket import WebsocketPool
from inventory import DropsCampaign
from utils import task_wrapper, timestamp, AwaitableValue, OrderedSet
from exceptions import RequestException, LoginException, CaptchaRequired
from constants import (
    GQL_URL,
    AUTH_URL,
    CLIENT_ID,
    USER_AGENT,
    COOKIES_PATH,
    GQL_OPERATIONS,
    MAX_WEBSOCKETS,
    WATCH_INTERVAL,
    WS_TOPICS_LIMIT,
    DROPS_ENABLED_TAG,
    State,
    WebsocketTopic,
)

if TYPE_CHECKING:
    from collections import abc
    from datetime import datetime
    from typing import Final, cast

    from utils import Game
    from gui import LoginForm
    from main import ParsedArgs
    from inventory import TimedDrop
    from constants import JsonType, GQLOperation


logger = logging.getLogger("TwitchDrops")
gql_logger = logging.getLogger("TwitchDrops.gql")


def viewers_key(channel: Channel) -> int:
    viewers = channel.viewers
    if viewers is not None:
        return viewers
    return -1


class Twitch:
    def __init__(self, options: ParsedArgs):
        self.options = options
        # State management
        self._state: State = State.IDLE
        self._state_change = asyncio.Event()
        self.game: Game | None = None
        self.inventory: dict[Game, list[DropsCampaign]] = {}
        # GUI
        self.gui = GUIManager(self)
        # Cookies, session and auth
        self._session: aiohttp.ClientSession | None = None
        self._access_token: str | None = None
        self._user_id: int | None = None
        self._is_logged_in = asyncio.Event()
        # Storing and watching channels
        self.channels: OrderedDict[int, Channel] = OrderedDict()
        self.watching_channel: AwaitableValue[Channel] = AwaitableValue()
        self._watching_task: asyncio.Task[None] | None = None
        self._watching_restart = asyncio.Event()
        self._drop_update: asyncio.Future[bool] | None = None
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
        await asyncio.sleep(start_time + 0.5 - time())

    def wait_until_login(self):
        return self._is_logged_in.wait()

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

    async def run(self):
        """
        Main method that runs the whole client.

        Here, we manage several things, specifically:
        • Fetching the drops inventory to make sure that everything we can claim, is claimed
        • Selecting a stream to watch, and watching it
        • Changing the stream that's being watched if necessary
        """
        self.gui.start()
        await self.check_login()
        if self._watching_task is not None:
            self._watching_task.cancel()
        self._watching_task = asyncio.create_task(self._watch_loop())
        # Add default topics
        assert self._user_id is not None
        self.websocket.add_topics([
            WebsocketTopic("User", "Drops", self._user_id, self.process_drops),
            WebsocketTopic("User", "CommunityPoints", self._user_id, self.process_points),
        ])
        first_select: bool = True
        full_cleanup: bool = False
        channels: Final[OrderedDict[int, Channel]] = self.channels
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
                games: list[Game] = []
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
                # 'games' has all games we can mine drops for
                # if it's empty, there's no point in continuing
                if not games:
                    self.gui.print("No active campaigns to mine drops for.")
                    return
                # only start the websocket after we confirm there are drops to mine
                await self.websocket.start()
                self.gui.games.set_games(games)
                self.change_state(State.GAME_SELECT)
            elif self._state is State.GAME_SELECT:
                self.game = self.gui.games.get_selection()
                if self.game is None:
                    if first_select:
                        # on first select, let the user make the choice
                        first_select = False
                    else:
                        self.game = self.gui.games.set_first()
                if self.game is not None:
                    # restart the watch loop immediately on new game selected
                    self.restart_watching()
                # signal channel cleanup that we're removing everything
                full_cleanup = True
                self.change_state(State.CHANNELS_CLEANUP)
            elif self._state is State.CHANNELS_CLEANUP:
                if self.game is None or full_cleanup:
                    # no game selected or we're doing full cleanup: remove everything
                    to_remove: list[Channel] = list(channels.values())
                else:
                    # remove all channels that:
                    to_remove = [
                        channel
                        for channel in channels.values()
                        if (
                            not channel.priority  # aren't prioritized
                            and (
                                channel.offline  # and are offline
                                # or online but aren't streaming the game we want anymore
                                or (channel.game is None or channel.game != self.game)
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
                if self.game is not None:
                    self.change_state(State.CHANNELS_FETCH)
                else:
                    # with no game selected, we switch to IDLE after cleanup
                    self.change_state(State.IDLE)
            elif self._state is State.CHANNELS_FETCH:
                if self.game is None:
                    self.change_state(State.GAME_SELECT)
                else:
                    # pre-display the active drop without substracting a minute
                    if (active_drop := self.get_active_drop()) is not None:
                        active_drop.display(countdown=False)
                    # gather ACLs from campaigns
                    # NOTE: we consider only campaigns that can be progressed
                    no_acl = False
                    new_channels: OrderedSet[Channel] = OrderedSet()
                    for campaign in self.inventory[self.game]:
                        if any(drop.can_earn() for drop in campaign.drops):
                            acl = campaign.allowed_channels
                            if acl:
                                new_channels.update(acl)
                            else:
                                no_acl = True
                    # set them online if possible
                    await asyncio.gather(*(channel.check_online() for channel in new_channels))
                    if no_acl:
                        # if there's at least one campaign without an ACL,
                        # add a list of live channels with drops enabled
                        new_channels.update(await self.get_live_streams())
                    # merge current channels into new ones
                    new_channels.update(self.channels.values())
                    # sort them descending by viewers,
                    # then by priority so that prioritized ones are first
                    # NOTE: We can drop OrderedSet now because there's no more channels being added
                    ordered_channels: list[Channel] = sorted(
                        new_channels, key=viewers_key, reverse=True
                    )
                    ordered_channels.sort(key=lambda ch: ch.priority, reverse=True)
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
                    # set our new channel list
                    channels.clear()
                    self.gui.channels.clear()
                    self.gui.channels.shrink()
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
                    watching_channel = self.watching_channel.get_with_default(None)
                    if watching_channel is not None:
                        new_watching = channels.get(watching_channel.id)
                        if new_watching is not None and self.can_watch(new_watching):
                            self.watch(new_watching)
                        else:
                            # we're removing a channel we're watching
                            self.stop_watching()
                    # pre-display the active drop again with a substracted minute
                    for channel in channels.values():
                        # check if there's any channels we can watch first
                        if self.can_watch(channel):
                            if (active_drop := self.get_active_drop(channel)) is not None:
                                active_drop.display(countdown=False, subone=True)
                            break
                    self.change_state(State.CHANNEL_SWITCH)
            elif self._state is State.CHANNEL_SWITCH:
                if self.game is None:
                    self.change_state(State.GAME_SELECT)
                else:
                    # Change into the selected channel, stay in the watching channel,
                    # or select a new channel that meets the required conditions
                    priority_channels: list[Channel] = []
                    selected_channel = self.gui.channels.get_selection()
                    if selected_channel is not None:
                        self.gui.channels.clear_selection()
                        priority_channels.append(selected_channel)
                    watching_channel = self.watching_channel.get_with_default(None)
                    if watching_channel is not None:
                        priority_channels.append(watching_channel)
                    # If there's no selected channel, change into a channel we can watch
                    for channel in chain(priority_channels, channels.values()):
                        if self.can_watch(channel):
                            self.watch(channel)
                            # break the state change chain by clearing the flag
                            self._state_change.clear()
                            break
                    else:
                        self.stop_watching()
                        self.gui.print(
                            f"No suitable channel to watch for game: {self.game}\n"
                            "Waiting for an ONLINE channel..."
                        )
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
                    drop_data: JsonType | None = (
                        context["data"]["currentUser"]["dropCurrentSession"]
                    )
                    if drop_data is not None:
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
                    if (drop := self.get_active_drop()) is not None:
                        drop.bump_minutes()
                        drop.display()
                    else:
                        logger.error("Active drop search failed")
            if i % 30 == 1:
                # ensure every 30 minutes that we don't have unclaimed points bonus
                await channel.claim_bonus()
            if i % 60 == 0:
                # refresh inventory and cleanup channels every hour
                self.change_state(State.INVENTORY_FETCH)
            i = (i + 1) % 3600
            await self._watch_sleep(last_watch + interval - time())

    def can_watch(self, channel: Channel) -> bool:
        if self.game is None:
            return False
        return (
            channel.online  # steam online
            and channel.drops_enabled  # drops are enabled
            # it's a game we've selected
            and channel.game is not None
            and channel.game == self.game
            # we can progress any campaign for the selected game
            and any(
                drop.can_earn(channel)
                for campaign in self.inventory[self.game]
                for drop in campaign.drops
            )
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
        watching_channel = self.watching_channel.get_with_default(None)
        if (
            (
                self._state is State.IDLE  # we're currently idle
                or channel.priority  # or this channel has priority
                and watching_channel is not None  # and we're watching...
                and not watching_channel.priority   # ... a non-priority channel
            ) and self.can_watch(channel)
        ):
            self.gui.print(f"{channel.name} goes ONLINE, switching...")
            self.watch(channel)

    def on_offline(self, channel: Channel):
        """
        Called by a Channel when it goes offline.
        """
        # change the channel if we're currently watching it
        watching_channel = self.watching_channel.get_with_default(None)
        if watching_channel is not None and watching_channel == channel:
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
        drop: TimedDrop | None = self.get_drop(drop_id)
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
            self.gui.print(f"Earned points for watching: {points:3}, total: {balance}")
        elif msg_type == "claim-available":
            claim_data = message["data"]["claim"]
            points = claim_data["point_gain"]["total_points"]
            await self.claim_points(claim_data["channel_id"], claim_data["id"])
            self.gui.print(f"Claimed bonus points: {points}")

    async def _login(self) -> str:
        logger.debug("Login flow started")
        login_form: LoginForm = self.gui.login

        payload: JsonType = {
            "client_id": CLIENT_ID,
            "undelete_user": False,
            "remember_me": True,
        }

        while True:
            username, password, token = await login_form.ask_login()
            payload["username"] = username
            payload["password"] = password
            # remove stale 2FA tokens, if present
            payload.pop("authy_token", None)
            payload.pop("twitchguard_code", None)
            for attempt in range(2):
                async with self.request("POST", f"{AUTH_URL}/login", json=payload) as response:
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
                        login_form.clear(password=True)
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
                        login_form.clear(token=True)
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
                    login_form.clear()
                    return self._access_token

    async def check_login(self) -> None:
        if self._access_token is not None and self._user_id is not None:
            # we're all good
            return
        # looks like we're missing something
        login_form: LoginForm = self.gui.login
        logger.debug("Checking login")
        login_form.update("Logging in...", None)
        if self._session is None:
            await self.initialize()
        assert self._session is not None
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
            async with self.request(
                "GET",
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
        login_form.update("Logged in", self._user_id)
        # update our cookie and save it
        jar.update_cookies(cookie, URL("https://twitch.tv"))
        jar.save(COOKIES_PATH)

    @asynccontextmanager
    async def request(
        self, method: str, url: str, *, attempts: int = 5, **kwargs
    ) -> abc.AsyncIterator[aiohttp.ClientResponse]:
        if self._session is None:
            await self.initialize()
        session = self._session
        assert session is not None
        method = method.upper()
        cause: Exception | None = None
        for attempt in range(attempts):
            logger.debug(f"Request: ({method=}, {url=}, {attempts=}, {kwargs=})")
            try:
                async with session.request(method, url, **kwargs) as response:
                    logger.debug(f"Response: {response.status}: {response}")
                    yield response
                return
            except aiohttp.ClientConnectionError as exc:
                cause = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(0.1 * attempt)
        raise RequestException(
            "Ran out of attempts while handling a request: "
            f"({method=}, {url=}, {attempts=}, {kwargs=})"
        ) from cause

    async def gql_request(self, op: GQLOperation) -> JsonType:
        headers = {
            "Authorization": f"OAuth {self._access_token}",
            "Client-Id": CLIENT_ID,
        }
        gql_logger.debug(f"GQL Request: {op}")
        async with self.request("POST", GQL_URL, json=op, headers=headers) as response:
            response_json: JsonType = await response.json()
        gql_logger.debug(f"GQL Response: {response_json}")
        return response_json

    async def fetch_campaign(
        self, campaign_id: str, claimed_benefits: dict[str, datetime]
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
        available_campaigns: set[str] = set(
            c["id"] for c in data
            if c["status"] in applicable_statuses and c["self"]["isAccountConnected"]
        )
        # fetch in-progress campaigns (inventory)
        response = await self.gql_request(GQL_OPERATIONS["Inventory"])
        inventory = response["data"]["currentUser"]["inventory"]
        ongoing_campaigns = inventory["dropCampaignsInProgress"] or []
        # this contains claimed benefit edge IDs, not drop IDs
        claimed_benefits: dict[str, datetime] = {
            b["id"]: timestamp(b["lastAwardedAt"]) for b in inventory["gameEventDrops"]
        }
        campaigns: list[DropsCampaign] = [
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

    def get_drop(self, drop_id: str) -> TimedDrop | None:
        """
        Returns a drop from the inventory, based on it's ID.
        """
        # try it with the currently selected game first
        if self.game is not None:
            for campaign in self.inventory[self.game]:
                if (drop := campaign.get_drop(drop_id)) is not None:
                    return drop
        # fallback to checking all campaigns
        for campaign in chain(*self.inventory.values()):
            if (drop := campaign.get_drop(drop_id)) is not None:
                return drop
        return None

    def get_active_drop(self, channel: Channel | None = None) -> TimedDrop | None:
        if self.game is None:
            return None
        watching_channel = self.watching_channel.get_with_default(channel)
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

    async def get_live_streams(self) -> list[Channel]:
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

    async def claim_points(self, channel_id: str | int, claim_id: str) -> None:
        await self.gql_request(
            GQL_OPERATIONS["ClaimCommunityPoints"].with_variables(
                {"input": {"channelID": str(channel_id), "claimID": claim_id}}
            )
        )
