from __future__ import annotations

import re
import asyncio
import logging
import validators
from base64 import b64encode
from functools import cached_property
from typing import Any, SupportsInt, TYPE_CHECKING

from utils import invalidate_cache, json_minify, Game
from exceptions import MinerException, RequestException
from constants import CALL, GQL_OPERATIONS, ONLINE_DELAY, URLType

if TYPE_CHECKING:
    from twitch import Twitch
    from gui import ChannelList
    from constants import JsonType


logger = logging.getLogger("TwitchDrops")


class Stream:
    __slots__ = ("channel", "broadcast_id", "viewers", "drops_enabled", "game", "title")

    def __init__(
        self,
        channel: Channel,
        *,
        id: SupportsInt,
        game: JsonType | None,
        viewers: int,
        title: str,
    ):
        self.channel: Channel = channel
        self.broadcast_id = int(id)
        self.viewers: int = viewers
        self.drops_enabled: bool = False
        self.game: Game | None = Game(game) if game else None
        self.title: str = title

    @classmethod
    def from_get_stream(cls, channel: Channel, data: JsonType) -> Stream:
        stream = data["stream"]
        settings = data["broadcastSettings"]
        return cls(
            channel,
            id=stream["id"],
            game=settings["game"],
            viewers=stream["viewersCount"],
            title=settings["title"],
        )

    @classmethod
    def from_directory(
        cls, channel: Channel, data: JsonType, *, drops_enabled: bool = False
    ) -> Stream:
        self = cls(
            channel,
            id=data["id"],
            game=data["game"],  # has to be there since we searched with it
            viewers=data["viewersCount"],
            title=data["title"],
        )
        self.drops_enabled = drops_enabled
        return self

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.broadcast_id == other.broadcast_id
        return NotImplemented


class Channel:
    def __init__(
        self,
        twitch: Twitch,
        *,
        id: SupportsInt,
        login: str,
        display_name: str | None = None,
        acl_based: bool = False,
    ):
        self._twitch: Twitch = twitch
        self._gui_channels: ChannelList = twitch.gui.channels
        self.id: int = int(id)
        self._login: str = login
        self._display_name: str | None = display_name
        self._spade_url: URLType | None = None
        self.points: int | None = None
        self._stream: Stream | None = None
        self._pending_stream_up: asyncio.Task[Any] | None = None
        # ACL-based channels are:
        # • considered first when switching channels
        # • if we're watching a non-based channel, a based channel going up triggers a switch
        # • not cleaned up unless they're streaming a game we haven't selected
        self.acl_based: bool = acl_based

    @classmethod
    def from_acl(cls, twitch: Twitch, data: JsonType) -> Channel:
        return cls(
            twitch,
            id=data["id"],
            login=data["name"],
            display_name=data.get("displayName"),
            acl_based=True,
        )

    @classmethod
    def from_directory(
        cls, twitch: Twitch, data: JsonType, *, drops_enabled: bool = False
    ) -> Channel:
        channel = data["broadcaster"]
        self = cls(
            twitch, id=channel["id"], login=channel["login"], display_name=channel["displayName"]
        )
        self._stream = Stream.from_directory(self, data, drops_enabled=drops_enabled)
        return self

    @classmethod
    async def from_name(
        cls, twitch: Twitch, channel_login: str, *, acl_based: bool = False
    ) -> Channel:
        self = cls(twitch, id=0, login=channel_login, acl_based=acl_based)
        # id and display name to be filled/overwritten by get_stream
        stream = await self.get_stream()
        if stream is not None:
            self._stream = stream
        return self

    def __repr__(self) -> str:
        if self._display_name is not None:
            name = f"{self._display_name}({self._login})"
        else:
            name = self._login
        return f"Channel({name}, {self.id})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return self.id

    @property
    def name(self) -> str:
        if self._display_name is not None:
            return self._display_name
        return self._login

    @property
    def url(self) -> URLType:
        return URLType(f"{self._twitch._client_type.CLIENT_URL}/{self._login}")

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
        return self._stream is None and self._pending_stream_up is not None

    @property
    def game(self) -> Game | None:
        if self._stream is not None:
            return self._stream.game
        return None

    @property
    def viewers(self) -> int | None:
        if self._stream is not None:
            return self._stream.viewers
        return None

    @viewers.setter
    def viewers(self, value: int):
        if self._stream is not None:
            self._stream.viewers = value

    @property
    def drops_enabled(self) -> bool:
        if self._stream is not None:
            return self._stream.drops_enabled
        return False

    def display(self, *, add: bool = False):
        self._gui_channels.display(self, add=add)

    def remove(self):
        if self._pending_stream_up is not None:
            self._pending_stream_up.cancel()
            self._pending_stream_up = None
        self._gui_channels.remove(self)

    async def get_spade_url(self) -> URLType:
        """
        To get this monstrous thing, you have to walk a chain of requests.
        Streamer page (HTML) --parse-> Streamer Settings (JavaScript) --parse-> Spade URL

        For mobile view, spade_url is available immediately from the page, skipping step #2.
        """
        SETTINGS_PATTERN: str = (
            r'src="(https://[\w.]+/config/settings\.[0-9a-f]{32}\.js)"'
        )
        SPADE_PATTERN: str = (
            r'"spade_?url": ?"(https://video-edge-[.\w\-/]+\.ts(?:\?allow_stream=true)?)"'
        )
        async with self._twitch.request("GET", self.url) as response1:
            streamer_html: str = await response1.text(encoding="utf8")
        match = re.search(SPADE_PATTERN, streamer_html, re.I)
        if not match:
            match = re.search(SETTINGS_PATTERN, streamer_html, re.I)
            if not match:
                raise MinerException("Error while spade_url extraction: step #1")
            streamer_settings = match.group(1)
            async with self._twitch.request("GET", streamer_settings) as response2:
                settings_js: str = await response2.text(encoding="utf8")
            match = re.search(SPADE_PATTERN, settings_js, re.I)
            if not match:
                raise MinerException("Error while spade_url extraction: step #2")
        return URLType(match.group(1))

    async def get_stream(self) -> Stream | None:
        try:
            response: JsonType = await self._twitch.gql_request(
                GQL_OPERATIONS["GetStreamInfo"].with_variables({"channel": self._login})
            )
        except MinerException as exc:
            raise MinerException(f"Channel: {self._login}") from exc
        stream_data: JsonType | None = response["data"]["user"]
        if not stream_data:
            return None
        # fill in channel_id and display name
        self.id = int(stream_data["id"])
        self._display_name = stream_data["displayName"]
        if not stream_data["stream"]:
            return None
        stream = Stream.from_get_stream(self, stream_data)
        if not stream.drops_enabled:
            try:
                available_drops: JsonType = await self._twitch.gql_request(
                    GQL_OPERATIONS["AvailableDrops"].with_variables({"channelID": str(self.id)})
                )
            except MinerException:
                logger.log(CALL, f"AvailableDrops GQL call failed for channel: {self._login}")
            else:
                stream.drops_enabled = any(
                    bool(c["timeBasedDrops"])
                    for c in (available_drops["data"]["channel"]["viewerDropCampaigns"] or [])
                )
        return stream

    async def update_stream(self, *, trigger_events: bool) -> bool:
        """
        Fetches the current channel stream, and if one exists,
        updates it's game, title, tags and viewers. Updates channel status in general.

        Setting 'trigger_events' to True will trigger on_online and on_offline events,
        if the new status differs from the one set before the call.
        """
        old_stream = self._stream
        self._stream = await self.get_stream()
        invalidate_cache(self, "_payload")
        if trigger_events:
            self._twitch.on_channel_update(self, old_stream, self._stream)
        return self._stream is not None

    async def _online_delay(self):
        """
        The 'stream-up' event is sent before the stream actually goes online,
        so just wait a bit and check if it's actually online by then.
        """
        await asyncio.sleep(ONLINE_DELAY.total_seconds())
        self._pending_stream_up = None  # for 'display' to work properly
        await self.update_stream(trigger_events=True)  # triggers 'display' via the event

    def check_online(self):
        """
        Sets up a task that will wait ONLINE_DELAY duration,
        and then check for the stream being ONLINE OR OFFLINE.

        If the channel is OFFLINE, it sets the channel's status to PENDING_ONLINE,
        where after ONLINE_DELAY, it's going to be set to ONLINE.
        If the channel is ONLINE already, after ONLINE_DELAY,
        it's status is going to be double-checked to ensure it's actually ONLINE.

        This is called externally, if we receive an event about the status possibly being ONLINE
        or having to be updated.
        """
        if self._pending_stream_up is None:
            self._pending_stream_up = asyncio.create_task(self._online_delay())
            self.display()

    def set_offline(self):
        """
        Sets the channel status to OFFLINE. Cancels PENDING_ONLINE if applicable.

        This is called externally, if we receive an event indicating the channel is now OFFLINE.
        """
        needs_display: bool = False
        if self._pending_stream_up is not None:
            self._pending_stream_up.cancel()
            self._pending_stream_up = None
            needs_display = True
        if self.online:
            old_stream = self._stream
            self._stream = None
            invalidate_cache(self, "_payload")
            self._twitch.on_channel_update(self, old_stream, self._stream)
            needs_display = False
        if needs_display:
            self.display()

    async def claim_bonus(self):
        """
        This claims bonus points if they're available, and fills out the 'points' attribute.
        """
        response: JsonType = await self._twitch.gql_request(
            GQL_OPERATIONS["ChannelPointsContext"].with_variables({"channelLogin": self._login})
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
    def _payload(self) -> JsonType:
        assert self._stream is not None
        payload = [
            {
                "event": "minute-watched",
                "properties": {
                    "broadcast_id": str(self._stream.broadcast_id),
                    "channel_id": str(self.id),
                    "channel": self._login,
                    "hidden": False,
                    "live": True,
                    "location": "channel",
                    "logged_in": True,
                    "muted": False,
                    "player": "site",
                    "user_id": self._twitch._auth_state.user_id,
                }
            }
        ]
        return {"data": (b64encode(json_minify(payload).encode("utf8"))).decode("utf8")}

    async def send_watch(self) -> bool:
        """
        Start of fix for 2024/5 API Change
        """
        try:
            response: JsonType = await self._twitch.gql_request(        # Gets signature and value
                GQL_OPERATIONS["PlaybackAccessToken"].with_variables({"login": self._login})
                )
        except MinerException as exc:
            raise MinerException(f"Channel: {self._login}") from exc
        signature: JsonType | None = response["data"]['streamPlaybackAccessToken']["signature"]
        value: JsonType | None = response["data"]['streamPlaybackAccessToken']["value"]
        if not signature or not value:
            return False

        RequestBroadcastQualitiesURL = f"https://usher.ttvnw.net/api/channel/hls/{self._login}.m3u8?sig={signature}&token={value}"

        try:
            async with self._twitch.request(                            # Gets list of streams
                "GET", RequestBroadcastQualitiesURL
            ) as response1:
                BroadcastQualities = await response1.text()
        except RequestException:
            return False
        
        BroadcastLowestQualityURL = BroadcastQualities.split("\n")[-1]  # Just takes the last line, this could probably be handled better in the future
        if not validators.url(BroadcastLowestQualityURL):
            return False

        try:
            async with self._twitch.request(                            # Gets actual streams
                "GET", BroadcastLowestQualityURL
            ) as response2:
                StreamURLList = await response2.text()
        except RequestException:
            return False

        StreamLowestQualityURL = StreamURLList.split("\n")[-2] # For whatever reason this includes a blank line at the end, this should probably be handled better in the future
        if not validators.url(StreamLowestQualityURL):
            return False

        try:
            async with self._twitch.request(                            # Downloads the stream
                "HEAD", StreamLowestQualityURL
            ) as response3:                                             # I lied, well idk, but this code doesn't listen for the actual video data
                return response3.status == 200
        except RequestException:
            return False
        """
        End of fix for 2024/5 API Change.
        Old code below.
        """

        """
        This uses the encoded payload on spade url to simulate watching the stream.
        Optimally, send every 60 seconds to advance drops.
        """
        if not self.online:
            return False
        if self._spade_url is None:
            self._spade_url = await self.get_spade_url()
        logger.debug(f"Sending minute-watched to {self.name}")
        try:
            async with self._twitch.request(
                "POST", self._spade_url, data=self._payload
            ) as response:
                return response.status == 204
        except RequestException:
            return False
