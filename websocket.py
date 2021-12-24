from __future__ import annotations

import json
import random
import string
import asyncio
import logging
from time import time
from functools import wraps
from contextlib import suppress
from typing import Any, Optional, List, Dict, Set, Iterable, TYPE_CHECKING

from websockets.exceptions import ConnectionClosed, ConnectionClosedOK
from websockets.client import WebSocketClientProtocol, connect as websocket_connect

from inventory import TimedDrop
from exceptions import MinerException
from constants import (
    JsonType,
    WebsocketTopic,
    WEBSOCKET_URL,
    PING_INTERVAL,
    PING_TIMEOUT,
    MAX_WEBSOCKETS,
    WS_TOPICS_LIMIT,
)

if TYPE_CHECKING:
    from twitch import Twitch


ws_logger = logging.getLogger("TwitchDrops.websocket")
NONCE_CHARS = string.ascii_letters + string.digits


def create_nonce(length: int = 30) -> str:
    return ''.join(random.choices(NONCE_CHARS, k=length))


def task_wrapper(afunc):
    @wraps(afunc)
    async def wrapper(self: Websocket, *args, **kwargs):
        try:
            await afunc(self, *args, **kwargs)
        except Exception:
            ws_logger.exception("Exception in websocket task")
            raise  # raise up to the wrapping task
    return wrapper


class Websocket:
    def __init__(self, pool: WebsocketPool, index: int):
        self._pool = pool
        self._twitch = pool._twitch
        # websocket index
        self._idx: int = index
        # current websocket connection
        self._ws: WebSocketClientProtocol
        # set when there's an active websocket connection
        self._connected_flag = asyncio.Event()
        # set when the websocket needs to reconnect
        self._reconnect_requested = asyncio.Event()
        # set when the topics changed
        self._topics_changed = asyncio.Event()
        # ping timestamps
        self._next_ping: float = time()
        self._max_pong: float = self._next_ping + PING_TIMEOUT.total_seconds()
        # main task, responsible for receiving messages, sending them, and websocket ping
        self._handle_task: Optional[asyncio.Task[Any]] = None
        # topics stuff
        self.topics: Dict[str, WebsocketTopic] = {}
        self._submitted: Set[WebsocketTopic] = set()

    @property
    def connected(self) -> bool:
        return self._connected_flag.is_set()

    def wait_until_connected(self):
        return self._connected_flag.wait()

    def request_reconnect(self):
        ws_logger.warning(f"Websocket[{self._idx}] requested reconnect.")
        # reset our ping interval, so we send a PING after reconnect right away
        self._next_ping = time()
        self._reconnect_requested.set()

    async def start(self):
        if self.connected:
            return
        if self._handle_task is None:
            self._handle_task = asyncio.create_task(self._handle())
        await self.wait_until_connected()

    def start_nowait(self):
        if self.connected:
            return
        if self._handle_task is None:
            self._handle_task = asyncio.create_task(self._handle())

    async def stop(self):
        if self._ws is not None:
            await self._ws.close()
        if self._handle_task is not None:
            await self._handle_task
            self._handle_task = None

    def stop_nowait(self):
        if self._ws is not None:
            asyncio.create_task(self._ws.close())
        # note: this detaches the handle task, so we have to assume it closes properly
        self._handle_task = None

    @task_wrapper
    async def _handle(self):
        # ensure we're logged in before connecting
        await self._twitch.wait_until_login()
        ws_logger.info(f"Websocket[{self._idx}] connecting...")
        # Connect/Reconnect loop
        async for websocket in websocket_connect(WEBSOCKET_URL, ssl=True, ping_interval=None):
            websocket.BACKOFF_MAX = 3 * 60  # type: ignore  # 3 minutes
            self._ws = websocket
            try:
                try:
                    self._reconnect_requested.clear()
                    self._connected_flag.set()
                    while not self._reconnect_requested.is_set():
                        await self._handle_ping()
                        await self._handle_topics()
                        await self._handle_recv()
                finally:
                    self._submitted.clear()
                    self._connected_flag.clear()
                # A reconnect was requested
            except ConnectionClosed as exc:
                if isinstance(exc, ConnectionClosedOK):
                    if exc.rcvd_then_sent:
                        # server closed the connection, not us - reconnect
                        ws_logger.warning(f"Websocket[{self._idx}] disconnected.")
                    else:
                        # we closed it - exit
                        ws_logger.info(f"Websocket[{self._idx}] stopped.")
                        return
                if exc.rcvd is not None:
                    code = exc.rcvd.code
                elif exc.sent is not None:
                    code = exc.sent.code
                else:
                    code = -1
                ws_logger.warning(f"Websocket[{self._idx}] closed unexpectedly: {code}")
            except Exception:
                ws_logger.exception(f"Exception in Websocket[{self._idx}]")
            ws_logger.warning(f"Websocket[{self._idx}] reconnecting...")

    async def _handle_ping(self):
        now = time()
        if now >= self._next_ping:
            self._next_ping = now + PING_INTERVAL.total_seconds()
            self._max_pong = now + PING_TIMEOUT.total_seconds()  # wait for a PONG for up to 10s
            await self.send({"type": "PING"})
        elif now >= self._max_pong:
            # it's been more than 10s and there was no PONG
            self.request_reconnect()

    async def _handle_topics(self):
        if not self._topics_changed.is_set():
            # nothing to do
            return
        current: Set[WebsocketTopic] = set(self.topics.values())
        # handle removed topics
        removed = self._submitted.difference(current)
        if removed:
            topics_list = list(map(str, removed))
            ws_logger.debug(f"Websocket[{self._idx}]: Removing topics: {', '.join(topics_list)}")
            await self.send(
                {
                    "type": "UNLISTEN",
                    "data": {
                        "topics": topics_list,
                        "auth_token": self._twitch._access_token,
                    }
                }
            )
            self._submitted.difference_update(removed)
        # handle added topics
        added = current.difference(self._submitted)
        if added:
            topics_list = list(map(str, added))
            ws_logger.debug(f"Websocket[{self._idx}]: Adding topics: {', '.join(topics_list)}")
            await self.send(
                {
                    "type": "LISTEN",
                    "data": {
                        "topics": topics_list,
                        "auth_token": self._twitch._access_token,
                    }
                }
            )
            self._submitted.update(added)
        self._topics_changed.clear()

    async def _gather_recv(self, messages: List[JsonType]):
        """
        Gather incoming messages over the timeout specified.
        Note that there's no return value - this modifies `messages` in-place.
        """
        while True:
            raw_message = await self._ws.recv()
            message = json.loads(raw_message)
            ws_logger.debug(f"Websocket[{self._idx}] received: {message}")
            messages.append(message)

    def _handle_message(self, message):
        # request the assigned topic to process the response
        topic_process = self.topics.get(message["data"]["topic"])
        if topic_process is not None:
            # use a task to not block the websocket
            asyncio.create_task(topic_process(json.loads(message["data"]["message"])))

    async def _handle_recv(self):
        """
        Handle receiving messages from the websocket.
        """
        # listen over 0.5s for incoming messages
        messages: List[JsonType] = []
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._gather_recv(messages), timeout=0.5)
        # process them
        for message in messages:
            msg_type = message["type"]
            if msg_type == "MESSAGE":
                self._handle_message(message)
            elif msg_type == "PONG":
                # move the timestamp to something much later
                self._max_pong = self._next_ping
            elif msg_type == "RESPONSE":
                # no special handling for these (for now)
                pass
            elif msg_type == "RECONNECT":
                # We've received a reconnect request
                self.request_reconnect()
            else:
                ws_logger.warning(f"Websocket[{self._idx}] received unknown payload: {message}")

    def add_topics(self, topics_set: Set[WebsocketTopic]):
        while topics_set and len(self.topics) < WS_TOPICS_LIMIT:
            topic = topics_set.pop()
            self.topics[str(topic)] = topic
            self._topics_changed.set()

    def remove_topics(self, topics_set: Set[str]):
        existing = topics_set.intersection(self.topics.keys())
        if not existing:
            # nothing to remove from here
            return
        topics_set.difference_update(existing)
        for topic in existing:
            del self.topics[topic]
        self._topics_changed.set()

    async def send(self, message: JsonType):
        if self._ws is None:
            return
        if message["type"] != "PING":
            message["nonce"] = create_nonce()
        await self._ws.send(json.dumps(message, separators=(',', ':')))
        ws_logger.debug(f"Websocket[{self._idx}] sent: {message}")


class WebsocketPool:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._running = asyncio.Event()
        self.websockets: List[Websocket] = []

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def wait_until_connected(self):
        return self._running.wait()

    async def start(self):
        await self._twitch.wait_until_login()
        if self.running:
            return
        # Add default topics
        assert self._twitch._user_id is not None
        user_id = self._twitch._user_id
        self.add_topics([
            WebsocketTopic("User", "Drops", user_id, self.process_drops),
            WebsocketTopic("User", "CommunityPoints", user_id, self.process_points),
        ])
        self._running.set()
        await asyncio.gather(*(ws.start() for ws in self.websockets))

    async def stop(self):
        self._running.clear()
        await asyncio.gather(*(ws.stop() for ws in self.websockets))

    def add_topics(self, topics: Iterable[WebsocketTopic]):
        # ensure no topics end up duplicated
        topics_set = set(topics)
        if not topics_set:
            # nothing to add
            return
        topics_set.difference_update(*(ws.topics.values() for ws in self.websockets))
        if not topics_set:
            # none left to add
            return
        for ws_idx in range(MAX_WEBSOCKETS):
            if ws_idx < len(self.websockets):
                # just read it back
                ws = self.websockets[ws_idx]
            else:
                # create new
                ws = Websocket(self, ws_idx)
                if self.running:
                    ws.start_nowait()
                self.websockets.append(ws)
            # ask websocket to take any topics it can - this modifies the set in-place
            ws.add_topics(topics_set)
            # see if there's any leftover topics for the next websocket connection
            if not topics_set:
                return
        # if we're here, there were leftover topics after filling up all websockets
        raise MinerException("Maximum topics limit has been reached")

    def remove_topics(self, topics: Iterable[str]):
        topics_set = set(topics)
        if not topics_set:
            # nothing to remove
            return
        for ws in self.websockets:
            ws.remove_topics(topics_set)
        # count up all the topics - if we happen to have more websockets connected than needed,
        # stop the last one and recycle topics from it - repeat until we have enough
        recycled_topics: List[WebsocketTopic] = []
        while True:
            count = sum(len(ws.topics) for ws in self.websockets)
            if count <= (len(self.websockets) - 1) * WS_TOPICS_LIMIT:
                ws = self.websockets.pop()
                recycled_topics.extend(ws.topics.values())
                ws.stop_nowait()
            else:
                break
        if recycled_topics:
            self.add_topics(recycled_topics)

    @task_wrapper
    async def process_drops(self, user_id: int, message: JsonType):
        drop_id = message["data"]["drop_id"]
        drop: Optional[TimedDrop] = None
        for campaign in self._twitch.inventory:
            drop = campaign.get_drop(drop_id)
            if drop is not None:
                break
        else:
            ws_logger.warning(f"Drop with ID of {drop_id} not found!")
            return
        drop.update(message)
        msg_type = message["type"]
        campaign = drop.campaign
        if msg_type == "drop-progress":
            print(
                f"Drop: {drop.rewards_text()} ({campaign.claimed_drops}/{campaign.total_drops}): "
                f"{drop.progress:6.1%} ({drop.remaining_minutes} minutes remaining)"
            )
        elif msg_type == "drop-claim":
            await drop.claim()
            print(
                f"Claimed drop: {drop.rewards_text()} "
                f"({campaign.claimed_drops}/{campaign.total_drops})"
            )
            if campaign.remaining_drops == 0:
                self._twitch.reevaluate_campaigns()

    @task_wrapper
    async def process_points(self, user_id: int, message: JsonType):
        msg_type = message["type"]
        if msg_type == "points-earned":
            points = message["data"]["point_gain"]["total_points"]
            balance = message["data"]["balance"]["balance"]
            print(f"Earned points for watching: {points:3}, total: {balance}")
        elif msg_type == "claim-available":
            claim_data = message["data"]["claim"]
            points = claim_data["point_gain"]["total_points"]
            await self._twitch.claim_points(claim_data["channel_id"], claim_data["id"])
            print(f"Claimed bonus points: {points}")
