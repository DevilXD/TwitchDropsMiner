from __future__ import annotations

import re
import json
import asyncio
import logging
from time import time
from base64 import b64encode
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from inventory import Game
from exceptions import MinerException
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
        self.game: Optional[Game] = None
        if settings["game"] is not None:
            self.game = Game(settings["game"])
        self.title: str = settings["title"]
        self._timestamp = datetime.now(timezone.utc)

    @classmethod
    def from_directory(cls, channel: Channel, data: JsonType):
        self = super().__new__(cls)
        self._twitch = channel._twitch
        self.channel = channel
        self.broadcast_id = data["id"]
        self.viewers = data["viewersCount"]
        self.drops_enabled = any(tag["id"] == DROPS_ENABLED_TAG for tag in data["tags"])
        self.game = Game(data["game"])
        self.title = data["title"]
        self._timestamp = datetime.now(timezone.utc)
        return self


class Channel:
    async def __new__(cls, *args, **kwargs):
        """
        Enables __init__ to be async.
        The instance is returned after initialization completes.
        """
        self = super().__new__(cls)
        await self.__init__(*args, **kwargs)  # type: ignore
        return self

    async def __init__(self, twitch: Twitch, channel_name: str):  # type: ignore
        self._twitch: Twitch = twitch
        self.id: int = 0  # temp, to be filled by get_stream
        self.name: str = channel_name
        self.url: str = f"{BASE_URL}/{channel_name}"
        self._spade_url: Optional[str] = None
        self.points: Optional[int] = None
        self._stream: Optional[Stream] = None
        self._pending_stream_up: Optional[asyncio.Task[Any]] = None
        await self.get_stream()

    @classmethod
    def from_directory(cls, twitch: Twitch, data: JsonType):
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
        # this is responsible for the ID/Key of the columns inside channel list
        return str(self.id)

    @property
    def online(self) -> bool:
        """
        Returns True if the streamer is online and is currently streaming, False otherwise.
        """
        return self._stream is not None

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
    def drops_enabled(self) -> Optional[bool]:
        if self._stream is not None:
            return self._stream.drops_enabled
        return None

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
            self.id = int(stream_data["id"])  # fill channel_id
            if stream_data["stream"]:
                self._stream = Stream(self, stream_data)
            else:
                self._stream = None
        return self._stream

    async def check_online(self) -> bool:
        stream = await self.get_stream()
        if stream is None:
            return False
        return True

    async def _online_delay(self):
        self.display()
        await asyncio.sleep(ONLINE_DELAY.total_seconds())
        await self.check_online()
        self._pending_stream_up = None
        self.display()

    def set_online(self):
        if self.online or self.pending_online:
            # we're already online, or about to be
            return
        # stream-up is sent before the stream actually goes online, so just wait a bit
        # and check if it's actually online by then
        self._pending_stream_up = asyncio.create_task(self._online_delay())
        # display is called from within the task

    def set_offline(self):
        # to be called externally, if we receive an event about this happening
        if self._pending_stream_up is not None:
            self._pending_stream_up.cancel()
            self._pending_stream_up = None
        self._stream = None
        self.display()

    async def claim_bonus(self):
        # this also fills out the 'points' attribute
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
            # calling claim_points is going to refresh the display, so if we're not calling it,
            # we need to do it ourselves
            self.display()

    def _encode_payload(self):
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
        if self._spade_url is None:
            self._spade_url = await self.get_spade_url()
        logger.debug(f"Sending minute-watched to {self.name}")
        self._twitch._last_watch = time()
        async with self._twitch._session.post(
            self._spade_url, data=self._encode_payload()
        ) as response:
            return response.status == 204
