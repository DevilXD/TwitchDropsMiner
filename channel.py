from __future__ import annotations

import re
import json
import logging
from copy import copy
from base64 import b64encode
from datetime import datetime, timezone
from typing import Any, Optional, Dict, TYPE_CHECKING

from inventory import Game
from exceptions import MinerException
from constants import BASE_URL, GQL_OPERATIONS

if TYPE_CHECKING:
    from twitch import Twitch


logger = logging.getLogger("TwitchDrops")


class Stream:
    def __init__(self, channel: Channel, data: Dict[str, Any]):
        self._twitch = channel._twitch
        self.channel = channel
        stream = data["stream"]
        self.broadcast_id = int(stream["id"])
        self.viewer_count = stream["viewersCount"]
        self.drops_enabled = any(tag["localizedName"] == "Drops Enabled" for tag in stream["tags"])
        settings = data["broadcastSettings"]
        self.game: Game = Game(settings["game"])
        self.title = settings["title"]
        self._timestamp = datetime.now(timezone.utc)


class Channel:
    async def __new__(cls, *args, **kwargs):
        """
        Enables __init__ to be async.
        The instance is returned after initialization completes.
        """
        self = super().__new__(cls)
        await self.__init__(*args, **kwargs)
        return self

    async def __init__(self, twitch: Twitch, channel_name: str):  # type: ignore
        self._twitch: Twitch = twitch
        self.id: int = 0  # temp, to be filled by get_stream
        self.name: str = channel_name
        self.url: str = f"{BASE_URL}/{channel_name}"
        self._spade_url: str = await self.get_spade_url()
        self.stream: Optional[Stream] = None
        await self.get_stream()

    def __eq__(self, other: object):
        if isinstance(other, self.__class__):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, self.id))

    @property
    def online(self) -> bool:
        """
        Returns True if the streamer is online and is currently streaming, False otherwise.
        """
        return self.stream is not None

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
        op = copy(GQL_OPERATIONS["GetStreamInfo"].with_variables({"channel": self.name}))
        response = await self._twitch.gql_request(op)
        if response:
            stream_data = response["data"]["user"]
            self.id = int(stream_data["id"])  # fill channel_id
            if stream_data["stream"]:
                self.stream = Stream(self, stream_data)
            else:
                self.stream = None
        return self.stream

    async def check_online(self) -> bool:
        stream = await self.get_stream()
        if stream is None:
            return False
        return True

    def set_offline(self):
        # to be called externally, if we receive an event about this happening
        self.stream = None

    def _encode_payload(self):
        assert self.stream is not None
        assert self._twitch._user_id is not None
        payload = [
            {
                "event": "minute-watched",
                "properties": {
                    "channel_id": self.id,
                    "broadcast_id": self.stream.broadcast_id,
                    "player": "site",
                    "user_id": self._twitch._user_id,
                }
            }
        ]
        json_event = json.dumps(payload, separators=(",", ":"))
        return {"data": (b64encode(json_event.encode("utf8"))).decode("utf8")}

    async def _send_watch(self):
        """
        This uses the encoded payload on spade url to simulate watching the stream.
        Optimally, send every 60 seconds to advance drops.
        """
        if not self.online:
            return
        logger.debug(f"Sending minute-watched to {self.name}")
        async with self._twitch._session.post(
            self._spade_url, data=self._encode_payload()
        ) as response:
            return response.status == 204
