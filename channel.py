from __future__ import annotations

import re
import json
import asyncio
import logging
from base64 import b64encode
from functools import cached_property
from datetime import datetime, timezone
from typing import Any, Optional, SupportsInt, TYPE_CHECKING

import aiohttp

from exceptions import MinerException
from utils import Game, invalidate_cache
from constants import JsonType, BASE_URL, GQL_OPERATIONS, ONLINE_DELAY, DROPS_ENABLED_TAG

if TYPE_CHECKING:
    from twitch import Twitch


logger = logging.getLogger("TwitchDrops")


class Stream:
    def __init__(self, channel: Channel, data: JsonType):
        self._twitch: Twitch = channel._twitch
        self.channel: Channel = channel
        stream = data["stream"]
        self.broadcast_id = int(stream["id"])
        self.viewers: int = stream["viewersCount"]
        self.drops_enabled: bool = any(tag["id"] == DROPS_ENABLED_TAG for tag in stream["tags"])
        settings = data["broadcastSettings"]
        self.game: Optional[Game] = Game(settings["game"]) if settings["game"] else None
        self.title: str = settings["title"]
        self._timestamp = datetime.now(timezone.utc)

    @classmethod
    def from_directory(cls, channel: Channel, data: JsonType):
        self = super().__new__(cls)
        self._twitch = channel._twitch
        self.channel = channel
        self.broadcast_id = int(data["id"])
        self.viewers = data["viewersCount"]
        self.drops_enabled = any(tag["id"] == DROPS_ENABLED_TAG for tag in data["tags"])
        self.game = Game(data["game"])  # has to be there since we searched with it
        self.title = data["title"]
        self._timestamp = datetime.now(timezone.utc)
        return self


class Channel:
    def __init__(
        self, twitch: Twitch, channel_id: SupportsInt, channel_name: str, *, priority: bool = False
    ):
        self._twitch: Twitch = twitch
        self.id: int = int(channel_id)
        self.name: str = channel_name
        self.url: str = f"{BASE_URL}/{channel_name}"
        self._spade_url: Optional[str] = None
        self.points: Optional[int] = None
        self._stream: Optional[Stream] = None
        self._pending_stream_up: Optional[asyncio.Task[Any]] = None
        # Priority channels are:
        # • considered first when switching channels
        # • if we're watching a non-priority channel, a priority channel going up triggers a switch
        # • not cleaned up unless they're streaming a game we haven't selected
        self.priority: bool = priority

    @classmethod
    def from_directory(cls, twitch: Twitch, data: JsonType, *, priority: bool = False) -> Channel:
        self = super().__new__(cls)
        self._twitch = twitch
        channel = data["broadcaster"]
        self.id = int(channel["id"])
        self.name = channel["displayName"]
        self.url = f"{BASE_URL}/{self.name}"
        self._spade_url = None
        self.points = None
        self._stream = Stream.from_directory(self, data)
        self._pending_stream_up = None
        self.priority = priority
        return self

    @classmethod
    async def from_name(
        cls, twitch: Twitch, channel_name: str, *, priority: bool = False
    ) -> Channel:
        self = super().__new__(cls)
        self._twitch = twitch
        # self.id to be filled by get_stream
        self.name = channel_name
        self.url = f"{BASE_URL}/{channel_name}"
        self._spade_url = None
        self.points = None
        self._stream = None
        self._pending_stream_up = None
        self.priority = priority
        stream = await self.get_stream()
        if stream is not None:
            self._stream = stream
        return self

    def __repr__(self) -> str:
        return f"Channel({self.name}, {self.id})"

    def __eq__(self, other: object):
        if isinstance(other, self.__class__):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, self.id))

    @property
    def iid(self) -> str:
        """
        Returns a string to be used as ID/key of the columns inside channel list.
        """
        return str(self.id)

    @property
    def online(self) -> bool:
        """
        Returns True if the streamer is online and is currently streaming, False otherwise.
        """
        return self._stream is not None

    @property
    def offline(self) -> bool:
        """
        Returns True if the streamer is offline and isn't about to come online, False otherwise.
        """
        return self._stream is None and self._pending_stream_up is None

    @property
    def pending_online(self) -> bool:
        """
        Returns True if the streamer is about to go online (most likely), False otherwise.
        This is because 'stream-up' event is received way before
        stream information becomes available.
        """
        return self._pending_stream_up is not None

    @property
    def game(self) -> Optional[Game]:
        if self._stream is not None and self._stream.game is not None:
            return self._stream.game
        return None

    @property
    def viewers(self) -> Optional[int]:
        if self._stream is not None:
            return self._stream.viewers
        return None

    @viewers.setter
    def viewers(self, value: int):
        if self._stream is not None:
            self._stream.viewers = value
        self.display()

    @property
    def drops_enabled(self) -> bool:
        if self._stream is not None:
            return self._stream.drops_enabled
        return False

    def display(self):
        self._twitch.gui.channels.display(self)

    def remove(self):
        if self._pending_stream_up is not None:
            self._pending_stream_up.cancel()
            self._pending_stream_up = None
        self._twitch.gui.channels.remove(self)

    async def get_spade_url(self) -> str:
        """
        To get this monstrous thing, you have to walk a chain of requests.
        Streamer page (HTML) --parse-> Streamer Settings (JavaScript) --parse-> Spade URL
        """
        assert self._twitch._session is not None
        async with self._twitch._session.get(self.url) as response:
            streamer_html = await response.text(encoding="utf8")
        match = re.search(
            r'src="(https://static\.twitchcdn\.net/config/settings\.[0-9a-f]{32}\.js)"',
            streamer_html,
            re.I,
        )
        if not match:
            raise MinerException("Error while spade_url extraction: step #1")
        streamer_settings = match.group(1)
        async with self._twitch._session.get(streamer_settings) as response:
            settings_js = await response.text(encoding="utf8")
        match = re.search(
            r'"spade_url": ?"(https://video-edge-[.\w\-/]+\.ts)"', settings_js, re.I
        )
        if not match:
            raise MinerException("Error while spade_url extraction: step #2")
        return match.group(1)

    async def get_stream(self) -> Optional[Stream]:
        response = await self._twitch.gql_request(
            GQL_OPERATIONS["GetStreamInfo"].with_variables({"channel": self.name})
        )
        if response:
            stream_data = response["data"]["user"]
            # fill channel_id and name
            self.id = int(stream_data["id"])
            self.name = stream_data["displayName"]
            if stream_data["stream"]:
                return Stream(self, stream_data)
        return None

    async def check_online(self) -> bool:
        stream = await self.get_stream()
        if stream is None:
            invalidate_cache(self, "_payload")
            return False
        self._stream = stream
        return True

    async def _online_delay(self):
        """
        The 'stream-up' event is sent before the stream actually goes online,
        so just wait a bit and check if it's actually online by then.
        """
        await asyncio.sleep(ONLINE_DELAY.total_seconds())
        online = await self.check_online()
        self._pending_stream_up = None  # for 'display' to work properly
        self.display()
        if online:
            self._twitch.on_online(self)

    def set_online(self):
        """
        Sets the channel status to PENDING_ONLINE, where after ONLINE_DELAY,
        it's going to be set to ONLINE.

        This is called externally, if we receive an event about this happening.
        """
        if self.offline:
            self._pending_stream_up = asyncio.create_task(self._online_delay())
            self.display()

    def set_offline(self):
        """
        Sets the channel status to OFFLINE. Cancels PENDING_ONLINE if applicable.

        This is called externally, if we receive an event about this happening.
        """
        if self._pending_stream_up is not None:
            self._pending_stream_up.cancel()
            self._pending_stream_up = None
            self.display()
        if self.online:
            self._stream = None
            invalidate_cache(self, "_payload")
            self.display()
            self._twitch.on_offline(self)

    async def claim_bonus(self):
        """
        This claims bonus points if they're available, and fills out the 'points' attribute.
        """
        response = await self._twitch.gql_request(
            GQL_OPERATIONS["ChannelPointsContext"].with_variables({"channelLogin": self.name})
        )
        channel_data: JsonType = response["data"]["community"]["channel"]
        self.points = channel_data["self"]["communityPoints"]["balance"]
        claim_available: JsonType = (
            channel_data["self"]["communityPoints"]["availableClaim"]
        )
        if claim_available:
            await self._twitch.claim_points(channel_data["id"], claim_available["id"])
            logger.info("Claimed bonus points")
        else:
            # calling 'claim_points' is going to refresh the display via the websocket payload,
            # so if we're not calling it, we need to do it ourselves
            self.display()

    @cached_property
    def _payload(self):
        assert self._stream is not None
        payload = [
            {
                "event": "minute-watched",
                "properties": {
                    "channel_id": self.id,
                    "broadcast_id": self._stream.broadcast_id,
                    "player": "site",
                    "user_id": self._twitch._user_id,
                }
            }
        ]
        json_event = json.dumps(payload, separators=(",", ":"))
        return {"data": (b64encode(json_event.encode("utf8"))).decode("utf8")}

    async def send_watch(self) -> bool:
        """
        This uses the encoded payload on spade url to simulate watching the stream.
        Optimally, send every 60 seconds to advance drops.
        """
        if not self.online:
            return False
        session = self._twitch._session
        if session is None:
            return False
        if self._spade_url is None:
            self._spade_url = await self.get_spade_url()
        logger.debug(f"Sending minute-watched to {self.name}")
        for attempt in range(5):
            try:
                async with session.post(self._spade_url, data=self._payload) as response:
                    return response.status == 204
            except (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError):
                continue
        return False
