from __future__ import annotations

import asyncio
import logging
from math import ceil
from time import time
from functools import partial
from collections import abc, OrderedDict
from datetime import datetime, timedelta, timezone
from contextlib import suppress, asynccontextmanager
from typing import Final, NoReturn, cast, TYPE_CHECKING

import aiohttp
from yarl import URL

from gui import GUIManager
from channel import Channel
from websocket import WebsocketPool
from inventory import DropsCampaign
from exceptions import (
    MinerException, RequestException, LoginException, CaptchaRequired, ExitRequest
)
from utils import task_wrapper, timestamp, AwaitableValue, OrderedSet, ExponentialBackoff
from constants import (
    BASE_URL,
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
    from utils import Game
    from gui import LoginForm
    from settings import Settings
    from inventory import TimedDrop
    from constants import JsonType, GQLOperation


logger = logging.getLogger("TwitchDrops")
gql_logger = logging.getLogger("TwitchDrops.gql")


class Twitch:
    def __init__(self, settings: Settings):
        self.settings: Settings = settings
        # State management
        self._state: State = State.IDLE
        self._state_change = asyncio.Event()
        self.games: dict[Game, int] = {}
        self.inventory: list[DropsCampaign] = []
        self._drops: dict[str, TimedDrop] = {}
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
        # Maintenance task
        self._mnt_task: asyncio.Task[None] | None = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is not None:
            return self._session
        cookie_jar = aiohttp.CookieJar()
        if COOKIES_PATH.exists():
            cookie_jar.load(COOKIES_PATH)
        self._session = aiohttp.ClientSession(
            cookie_jar=cookie_jar,
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(connect=5, total=10),
        )
        return self._session

    async def shutdown(self) -> None:
        start_time = time()
        self.gui.print("Exiting...")
        self.stop_watching()
        if self._watching_task is not None:
            self._watching_task.cancel()
            self._watching_task = None
        if self._mnt_task is not None:
            self._mnt_task.cancel()
            self._mnt_task = None
        # close session, save cookies and stop websocket
        if self._session is not None:
            cookie_jar = cast(aiohttp.CookieJar, self._session.cookie_jar)
            cookie_jar.save(COOKIES_PATH)
            session, self._session = self._session, None
            await session.close()
        await self.websocket.stop()
        # save image cache
        self.gui.save()
        # wait at least half a second + whatever it takes to complete the closing
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
        closes it with X. Usually used solely to display tracebacks from the closing sequence.
        """
        self.gui.prevent_close()

    def print(self, *args, **kwargs):
        """
        Can be used to print messages within the GUI.
        """
        self.gui.print(*args, **kwargs)

    def save(self) -> None:
        """
        Saves the application state.
        """
        self.gui.save()
        self.settings.save()

    @staticmethod
    def _viewers_key(channel: Channel) -> int:
        if (viewers := channel.viewers) is not None:
            return viewers
        return -1

    def _game_key(self, channel: Channel) -> int:
        if (game := channel.game) is None:
            return 1
        elif game not in self.games:
            # in case a channel is gathered from an ACL and doesn't play the expected game,
            # we use the same priority as for non-prioritized games
            return 0
        return self.games[game]

    async def run(self):
        """
        Main method that runs the whole client.

        Here, we manage several things, specifically:
        • Fetching the drops inventory to make sure that everything we can claim, is claimed
        • Selecting a stream to watch, and watching it
        • Changing the stream that's being watched if necessary
        """
        self.gui.start()
        try:
            await self.check_login()
        except ExitRequest:
            # we've been requested to exit during login, most likely
            return
        await self.websocket.start()
        # NOTE: watch task is explicitly restarted on each new run
        if self._watching_task is not None:
            self._watching_task.cancel()
        self._watching_task = asyncio.create_task(self._watch_loop())
        # Add default topics
        assert self._user_id is not None
        self.websocket.add_topics([
            WebsocketTopic("User", "Drops", self._user_id, self.process_drops),
            WebsocketTopic("User", "CommunityPoints", self._user_id, self.process_points),
        ])
        full_cleanup: bool = False
        channels: Final[OrderedDict[int, Channel]] = self.channels
        self.change_state(State.INVENTORY_FETCH)
        while True:
            if self._state is State.IDLE:
                self.stop_watching()
                # clear the flag and wait until it's set again
                self._state_change.clear()
            elif self._state is State.INVENTORY_FETCH:
                # NOTE: maintenance task is restarted on inventory fetch
                if self._mnt_task is not None and not self._mnt_task.done():
                    self._mnt_task.cancel()
                self._mnt_task = asyncio.create_task(self._maintenance_task())
                await self.fetch_inventory()
                self.gui.set_games(set(campaign.game for campaign in self.inventory))
                # Save state on every inventory fetch
                self.save()
                self.change_state(State.GAMES_UPDATE)
            elif self._state is State.GAMES_UPDATE:
                # Figure out which games to watch, and claim the drops we can
                self.games.clear()
                priorities = self.gui.settings.priorities()
                # claim drops from expired and active campaigns
                for campaign in self.inventory:
                    if not campaign.upcoming:
                        for drop in campaign.drops:
                            if drop.can_claim:
                                await drop.claim()
                # collect games from active campaigns
                exclude = self.settings.exclude
                priority = self.settings.priority
                priority_only = self.settings.priority_only
                for campaign in self.inventory:
                    game = campaign.game
                    if (
                        game not in self.games  # isn't already there
                        and game.name not in exclude  # and isn't excluded
                        # and isn't excluded by priority_only
                        and (not priority_only or game.name in priority)
                        and campaign.can_earn()  # and can be progressed (active required)
                    ):
                        # non-excluded games with no priority, are placed last, below priority ones
                        self.games[game] = priorities.get(game.name, 0)
                full_cleanup = True
                self.restart_watching()
                self.change_state(State.CHANNELS_CLEANUP)
            elif self._state is State.CHANNELS_CLEANUP:
                if not self.games or full_cleanup:
                    # no games selected or we're doing full cleanup: remove everything
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
                                or (channel.game is None or channel.game not in self.games)
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
                if self.games:
                    self.change_state(State.CHANNELS_FETCH)
                else:
                    # with no games available, we switch to IDLE after cleanup
                    self.gui.print(
                        "No active campaigns to mine drops for. Waiting for an active campaign..."
                    )
                    self.change_state(State.IDLE)
            elif self._state is State.CHANNELS_FETCH:
                # start with all current channels
                new_channels: OrderedSet[Channel] = OrderedSet(self.channels.values())
                # gather and add ACL channels from campaigns
                # NOTE: we consider only campaigns that can be progressed
                # NOTE: we use another set so that we can set them online separately
                no_acl: set[Game] = set()
                acl_channels: OrderedSet[Channel] = OrderedSet()
                for campaign in self.inventory:
                    if campaign.game in self.games and campaign.can_earn():
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
                ordered_channels.sort(key=lambda ch: ch.priority, reverse=True)
                ordered_channels.sort(key=self._game_key)
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
                    for channel in sorted(channels.values(), key=self._game_key):
                        if self.can_watch(channel) and self.should_switch(channel):
                            new_watching = channel
                            break
                watching_channel = self.watching_channel.get_with_default(None)
                if watching_channel is None and new_watching is None:
                    # not watching anything and there isn't anything to watch either
                    self.gui.print(
                        "No available channels to watch. Waiting for an ONLINE channel..."
                    )
                    self.change_state(State.IDLE)
                else:
                    if new_watching is not None:
                        # if we have a better switch target - do so
                        # otherwise, continue watching what we had before
                        self.watch(new_watching)
                    # break the state change chain by clearing the flag
                    self._state_change.clear()
            elif self._state is State.EXIT:
                # we've been requested to exit the application
                break
            await self._state_change.wait()
        # post-main-loop code goes here

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
                    else:
                        logger.error("Active drop search failed")
            await self._watch_sleep(last_watch + interval - time())

    @task_wrapper
    async def _maintenance_task(self) -> None:
        # NOTE: this task is started anew / restarted on every inventory fetch
        # 1m sleep to let the application sort out the starting sequence and watching channel
        await asyncio.sleep(60)
        # figure out the maximum sleep period
        # 1h at max, but can be shorter if there's an upcoming campaign earlier than that
        # divide the period into up to two evenly spaced checks (usually ~15-30m)
        now = datetime.now(timezone.utc)
        one_hour = timedelta(hours=1)
        period = min(
            (campaign.starts_at - now for campaign in self.inventory if campaign.starts_at > now),
            default=one_hour,
        )
        if period > one_hour:
            period = one_hour
        times = ceil(period.total_seconds() / 30 * 60)
        period /= times
        for i in range(times):
            channel = self.watching_channel.get_with_default(None)
            # ensure every ~20-30 minutes that we don't have unclaimed points bonus
            if channel is not None:
                try:
                    await channel.claim_bonus()
                except asyncio.CancelledError:
                    raise  # let this one through
                except Exception:
                    pass  # we intentionally silently skip anything else
            await asyncio.sleep(period.total_seconds())
        # this triggers this task restart every 60 minutes
        self.change_state(State.INVENTORY_FETCH)

    def can_watch(self, channel: Channel) -> bool:
        """
        Determines if the given channel qualifies as a watching candidate.
        """
        if not self.games:
            return False
        return (
            channel.online  # steam online
            and channel.drops_enabled  # drops are enabled
            # it's one of the games we've selected
            and channel.game is not None and channel.game in self.games
            # we can progress any campaign for the selected game
            and any(campaign.can_earn(channel) for campaign in self.inventory)
        )

    def should_switch(self, channel: Channel) -> bool:
        """
        Determines if the given channel qualifies as a switch candidate.
        """
        watching_channel = self.watching_channel.get_with_default(None)
        channel_order = self._game_key(channel)
        if watching_channel is not None:
            watching_order = self._game_key(watching_channel)
        else:
            # stub it with some high value, it doesn't really matter
            # since 'is None' check returns earlier anyway
            watching_order = 1
        return (
            watching_channel is None  # there's no current watching channel
            # or this channel's game is higher order than the watching one's
            # NOTE: order is tied to the priority list position, so lower == higher
            or channel_order < watching_order
            or channel_order == watching_order  # or the order is the same
            # and this channel has priority over the watching channel
            and channel.priority > watching_channel.priority
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
                try:
                    async with self.request(
                        "POST", "https://passport.twitch.tv/login", json=payload
                    ) as response:
                        login_response: JsonType = await response.json()
                except aiohttp.ContentTypeError as exc:
                    raise MinerException(
                        "Unexpected content type returned instead of JSON, "
                        "usually due to being redirected. "
                        "Do you need to login for internet access?"
                    ) from exc

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
        # NOTE: We need this here because of the jar being accessed
        session = await self.get_session()
        url = URL(BASE_URL)
        assert url.host is not None
        jar = cast(aiohttp.CookieJar, session.cookie_jar)
        for attempt in range(2):
            cookie = jar.filter_cookies(url)
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
                    jar.clear_domain(url.host)
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
        jar.update_cookies(cookie, url)
        jar.save(COOKIES_PATH)

    @asynccontextmanager
    async def request(
        self, method: str, url: str, *, attempts: int = 5, **kwargs
    ) -> abc.AsyncIterator[aiohttp.ClientResponse]:
        session = await self.get_session()
        method = method.upper()
        if self.settings.proxy and "proxy" not in kwargs:
            kwargs["proxy"] = self.settings.proxy
        logger.debug(f"Request: ({method=}, {url=}, {attempts=}, {kwargs=})")
        attempt = 0
        cause: Exception | None = None
        backoff = ExponentialBackoff(shift=4, maximum=3*60)
        while attempt < attempts + 1:
            delay: float | None = None
            try:
                async with session.request(method, url, **kwargs) as response:
                    logger.debug(f"Response: {response.status}: {response}")
                    if response.status < 500:
                        yield response
                        return
                    delay = next(backoff)
                    self.print(f"Twitter is down, retrying in {round(delay)} seconds...")
            except asyncio.TimeoutError:
                delay = next(backoff)
                self.print(f"Cannot connect to Twitter, retrying in {round(delay)} seconds...")
            except aiohttp.ClientConnectionError as exc:
                cause = exc
            if delay is not None:
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(0.1 * attempt)
                attempt += 1
        if "json" in kwargs and "password" in kwargs["json"]:
            kwargs["json"]["password"] = "..."
        raise RequestException(
            "Ran out of attempts while handling a request: "
            f"({method=}, {url=}, {attempts=}, {kwargs=})"
        ) from cause

    async def gql_request(self, op: GQLOperation) -> JsonType:
        gql_logger.debug(f"GQL Request: {op}")
        async with self.request(
            "POST",
            "https://gql.twitch.tv/gql",
            json=op,
            headers={
                "Authorization": f"OAuth {self._access_token}",
                "Client-Id": CLIENT_ID,
            }
        ) as response:
            response_json: JsonType = await response.json()
        gql_logger.debug(f"GQL Response: {response_json}")
        return response_json

    async def fetch_campaign(
        self,
        campaign_id: str,
        available_data: JsonType,
        claimed_benefits: dict[str, datetime],
    ) -> DropsCampaign:
        response = await self.gql_request(
            GQL_OPERATIONS["CampaignDetails"].with_variables(
                {"channelLogin": str(self._user_id), "dropID": campaign_id}
            )
        )
        campaign_data: JsonType = response["data"]["user"]["dropCampaign"]
        # NOTE: we use available_data to add a couple of fields missing from the existing details,
        # most notably: game boxart
        campaign_data["game"]["boxArtURL"] = available_data["game"]["boxArtURL"]
        return DropsCampaign(self, campaign_data, claimed_benefits)

    async def fetch_inventory(self) -> None:
        # fetch in-progress campaigns (inventory)
        response = await self.gql_request(GQL_OPERATIONS["Inventory"])
        inventory: JsonType = response["data"]["currentUser"]["inventory"]
        ongoing_campaigns: list[JsonType] = inventory["dropCampaignsInProgress"] or []
        # this contains claimed benefit edge IDs, not drop IDs
        claimed_benefits: dict[str, datetime] = {
            b["id"]: timestamp(b["lastAwardedAt"]) for b in inventory["gameEventDrops"]
        }
        campaigns: list[DropsCampaign] = [
            DropsCampaign(self, campaign_data, claimed_benefits)
            for campaign_data in ongoing_campaigns
        ]
        # fetch all available campaigns data
        response = await self.gql_request(GQL_OPERATIONS["Campaigns"])
        available_list: list[JsonType] = response["data"]["currentUser"]["dropCampaigns"] or []
        applicable_statuses = ("ACTIVE", "UPCOMING")
        existing_campaigns: set[str] = set(c.id for c in campaigns)
        available_campaigns: dict[str, JsonType] = {
            c["id"]: c
            for c in available_list
            if (
                c["status"] in applicable_statuses  # that are currently ACTIVE
                and c["self"]["isAccountConnected"]  # and account is connected
                and c["id"] not in existing_campaigns  # and they aren't in the inventory already
            )
        }
        # add campaigns that remained, that can be earned but are not in-progress yet
        for campaign_id, available_data in available_campaigns.items():
            campaign = await self.fetch_campaign(campaign_id, available_data, claimed_benefits)
            if campaign.can_earn():
                campaigns.append(campaign)
        campaigns.sort(key=lambda c: c.ends_at)
        self._drops.clear()
        self.gui.inv.clear()
        self.inventory.clear()
        for campaign in campaigns:
            self._drops.update((drop.id, drop) for drop in campaign.drops)
            await self.gui.inv.add_campaign(campaign)
            self.inventory.append(campaign)

    def get_active_drop(self, channel: Channel | None = None) -> TimedDrop | None:
        if not self.games:
            return None
        watching_channel = self.watching_channel.get_with_default(channel)
        drops: list[TimedDrop] = []
        strict_drops: list[TimedDrop] = []
        game: Game | None = watching_channel is not None and watching_channel.game or None
        for campaign in self.inventory:
            if campaign.game in self.games and campaign.can_earn(watching_channel):
                new_drops = [drop for drop in campaign.drops if drop.can_earn(watching_channel)]
                drops.extend(new_drops)
                # 'strict_drops' has an additional condition - watching channel game must match
                # the campaign's game. If this list would end up empty,
                # we use 'drops' as a fallback without this extra condition.
                if game is not None and campaign.game == game:
                    strict_drops.extend(new_drops)
        if strict_drops:
            drops = strict_drops
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
