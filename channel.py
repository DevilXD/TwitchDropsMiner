from __future__ import annotations

import re
import gzip
import json
import asyncio
import logging
from enum import Enum, auto
from base64 import b64encode
from datetime import datetime, timezone
from functools import cached_property
from typing import Any, SupportsInt, cast, TYPE_CHECKING

import aiohttp
from yarl import URL

from utils import Game, json_minify, isonow
from exceptions import MinerException, RequestException
from constants import CALL, GQL_QUERIES, ONLINE_DELAY, URLType, GQLQuery

if TYPE_CHECKING:
    from twitch import Twitch
    from gui import ChannelList
    from constants import JsonType, GQLPersistedQuery


logger = logging.getLogger("TwitchDrops")


class ChannelStatus(Enum):
    """
    The presence of a channel, as far as the miner knows it.

    This used to be encoded implicitly in the combination of `_stream` and
    `_pending_stream_up`. Making it a named value means the GUI, the switch logic
    and the tests all agree on what "pending" means.
    """

    OFFLINE = auto()
    PENDING_ONLINE = auto()
    ONLINE = auto()


class Stream:
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
        self.drops_enabled: bool = not channel._twitch.settings.available_drops_check
        self.game: Game | None = Game(game) if game else None
        self.title: str = title
        self._stream_url: URLType | None = None

    @cached_property
    def _watch_payload(self) -> list[JsonType]:
        return [
            {
                "event": "minute-watched",
                "properties": {
                    "broadcast_id": str(self.broadcast_id),
                    "channel_id": str(self.channel.id),
                    "channel": self.channel._login,
                    "client_time": isonow(),
                    "game": self.game.name if self.game is not None else "",
                    "game_id": str(self.game.id) if self.game is not None else "",
                    "hidden": False,
                    "is_live": True,
                    "live": True,
                    "logged_in": True,
                    "minutes_logged": 1,
                    "muted": False,
                    "user_id": self.channel._twitch._auth_state.user_id,
                }
            }
        ]

    @cached_property
    def spade_payload(self) -> JsonType:
        return {
            "data": (b64encode(json_minify(self._watch_payload).encode("utf8"))).decode("utf8")
        }

    @cached_property
    def gql_payload(self) -> GQLQuery:
        return GQLQuery(
            (
                "\n mutation SendEvents($input: SendSpadeEventsInput!) "
                "{\n sendSpadeEvents(input: $input) {\n statusCode\n}\n}\n"
            ),
            b64encode(
                gzip.compress(json_minify(self._watch_payload).encode("utf8"))
            ).decode("utf8")
        )

    @classmethod
    def from_get_stream(cls, channel: Channel, channel_data: JsonType) -> Stream:
        stream = channel_data["stream"]
        settings = channel_data["broadcastSettings"]
        return cls(
            channel,
            id=stream["id"],
            game=settings["game"],
            viewers=stream["viewersCount"],
            title=settings["title"],
        )

    @classmethod
    def from_directory(
        cls, channel: Channel, channel_data: JsonType, *, drops_enabled: bool = False
    ) -> Stream:
        self = cls(
            channel,
            id=channel_data["id"],
            game=channel_data["game"],  # has to be there since we searched with it
            viewers=channel_data["viewersCount"],
            title=channel_data["title"],
        )
        self.drops_enabled = drops_enabled
        return self

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.broadcast_id == other.broadcast_id
        return NotImplemented

    async def get_stream_url(self) -> URLType | None:
        if self._stream_url is not None:
            return self._stream_url
        # get the stream playback access token from GQL
        playback_token_response: JsonType = await self.channel._twitch.gql_request(
            GQL_QUERIES["PlaybackAccessToken"].with_variables({"login": self.channel._login})
        )
        token_data: JsonType = playback_token_response["data"]["streamPlaybackAccessToken"]
        token_value = token_data["value"]
        token_signature = token_data["signature"]
        # using the token, query Twitch for a list of all available stream qualities
        available_qualities: str = ''
        try:
            async with self.channel._twitch.request(
                "GET",
                URL(
                    "https://usher.ttvnw.net/api/channel/hls/"
                    f"{self.channel._login}.m3u8?sig={token_signature}&token={token_value}"
                ),
            ) as qualities_response:
                available_qualities = await qualities_response.text()
            # try to decode the suspected JSON
            try:
                available_json: JsonType = json.loads(available_qualities)
            except json.JSONDecodeError:
                # No JSON: this is the expected path. Do nothing and continue with the below.
                pass
            else:
                # JSON was decoded - if there's an error, log it and report failure
                if isinstance(available_json, list):
                    available_json = available_json[0]
                if "error" in available_json:
                    logger.error(f"Stream URL get error: \"{available_json['error']}\"")
                    self.channel.set_offline()
                return None
            # pick the last URL from the list, usually with the lowest quality stream
            self._stream_url = cast(URLType, URL(available_qualities.strip().split("\n")[-1]))
        except (aiohttp.InvalidURL, ValueError):
            self.channel._twitch.print(available_qualities)
            raise
        return self._stream_url


class Channel:
    __slots__ = (
        "_twitch", "_gui_channels", "id", "_login", "_display_name", "_spade_url",
        "_stream", "_pending_stream_up", "_stream_generation", "_status_since", "acl_based"
    )

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
        self._stream: Stream | None = None
        self._pending_stream_up: asyncio.Task[Any] | None = None
        # Every external event that can invalidate an in-flight stream check bumps
        # this counter. The check captures it before awaiting the network and only
        # applies its result if the counter is still the same. This is what keeps a
        # slow ONLINE check from resurrecting a channel that has just gone OFFLINE.
        self._stream_generation: int = 0
        self._status_since: datetime = datetime.now(timezone.utc)
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
    def stream_gql(self) -> GQLPersistedQuery:
        return GQL_QUERIES["GetStreamInfo"].with_variables({"channel": self._login})

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
    def status(self) -> ChannelStatus:
        """
        The channel's presence, as a single explicit value.

        NOTE: A channel can be ONLINE while a re-check is pending. That's why the
        pending task is not folded into the status while `_stream` is available.
        """
        if self._stream is not None:
            return ChannelStatus.ONLINE
        if self._pending_stream_up is not None:
            return ChannelStatus.PENDING_ONLINE
        return ChannelStatus.OFFLINE

    @property
    def status_since(self) -> datetime:
        """When the current status was first observed (UTC)."""
        return self._status_since

    @property
    def online(self) -> bool:
        """
        Returns True if the streamer is online and is currently streaming, False otherwise.
        """
        return self.status is ChannelStatus.ONLINE

    @property
    def offline(self) -> bool:
        """
        Returns True if the streamer is offline and isn't about to come online, False otherwise.
        """
        return self.status is ChannelStatus.OFFLINE

    @property
    def pending_online(self) -> bool:
        """
        Returns True if the streamer is about to go online (most likely), False otherwise.
        This is because 'stream-up' event is received way before
        stream information becomes available.
        """
        return self.status is ChannelStatus.PENDING_ONLINE

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
        self._stream_generation += 1
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
        SETTINGS_PATTERN: str = r'src="(https://[\w.]+/config/settings\.[0-9a-f]{32}\.js)"'
        SPADE_PATTERN: str = r'"spade_?url": ?"(https://[.\w\-/]+)"'
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

    def _check_drops_enabled(self, available_drops: list[JsonType]) -> bool:
        return any(
            (
                (campaign := self._twitch._campaigns.get(campaign_data["id"])) is not None
                and campaign.can_earn(self, ignore_channel_status=True)
            )
            for campaign_data in available_drops
        )

    def _set_stream(self, stream: Stream | None) -> None:
        """
        Apply a stream value and keep the derived status timestamp coherent.
        """
        old_status = self.status
        self._stream = stream
        if self.status is not old_status:
            self._status_since = datetime.now(timezone.utc)

    def external_update(self, channel_data: JsonType, available_drops: list[JsonType]):
        """
        Update stream information based on data provided externally.

        Used for bulk-updates of channel statuses during reload.
        """
        # The payload is the newest truth we have - cancel and invalidate any
        # in-flight per-channel check so it can't overwrite this result.
        self._stream_generation += 1
        if self._pending_stream_up is not None:
            self._pending_stream_up.cancel()
            self._pending_stream_up = None
        if not channel_data["stream"]:
            self._set_stream(None)
            return
        stream = Stream.from_get_stream(self, channel_data)
        if not stream.drops_enabled:
            stream.drops_enabled = self._check_drops_enabled(available_drops)
        self._set_stream(stream)

    async def get_stream(self) -> Stream | None:
        try:
            response: JsonType = await self._twitch.gql_request(self.stream_gql)
        except MinerException as exc:
            raise MinerException(f"Channel: {self._login}") from exc
        channel_data: JsonType | None = response["data"]["user"]
        if not channel_data:
            return None
        # fill in display name
        if self._display_name is None:
            self._display_name = channel_data["displayName"]
        if not channel_data["stream"]:
            return None
        stream = Stream.from_get_stream(self, channel_data)
        if not stream.drops_enabled:
            try:
                available_drops_campaigns: JsonType = await self._twitch.gql_request(
                    GQL_QUERIES["AvailableDrops"].with_variables({"channelID": str(self.id)})
                )
            except MinerException:
                logger.log(CALL, f"AvailableDrops GQL call failed for channel: {self._login}")
            else:
                stream.drops_enabled = self._check_drops_enabled(
                    available_drops_campaigns["data"]["channel"]["viewerDropCampaigns"] or []
                )
        return stream

    async def update_stream(self, *, generation: int | None = None) -> bool:
        """
        Fetches the current channel stream, and if one exists,
        updates it's game, title, tags and viewers. Updates channel status in general.

        When `generation` is passed, the result is discarded if a newer event has
        invalidated this check while the request was in flight.
        """
        old_stream = self._stream
        new_stream = await self.get_stream()
        if generation is not None and generation != self._stream_generation:
            # A newer event (offline, or another check) won the race.
            return self._stream is not None
        self._set_stream(new_stream)
        self._twitch.on_channel_update(self, old_stream, self._stream)
        return self._stream is not None

    async def _online_delay(self, generation: int):
        """
        The 'stream-up' event is sent before the stream actually goes online,
        so just wait a bit and check if it's actually online by then.
        """
        await asyncio.sleep(ONLINE_DELAY.total_seconds())
        if generation != self._stream_generation:
            # Offline (or another check) happened while we were sleeping.
            # Only clear the pending slot if it still belongs to this check.
            if self._pending_stream_up is asyncio.current_task():
                self._pending_stream_up = None
            return
        self._pending_stream_up = None  # for 'display' to work properly
        await self.update_stream(generation=generation)

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
            # Deliberate debounce: events arriving while a check is already pending
            # do not extend or restart the delay; the check already scheduled will
            # read the freshest data when it fires.
            self._stream_generation += 1
            if self._stream is None:
                self._status_since = datetime.now(timezone.utc)
            self._pending_stream_up = asyncio.create_task(
                self._online_delay(self._stream_generation)
            )
            self.display()

    def set_offline(self):
        """
        Sets the channel status to OFFLINE. Cancels PENDING_ONLINE if applicable.

        This is called externally, if we receive an event indicating the channel is now OFFLINE.
        """
        # Any in-flight check now describes a past that we know is wrong.
        self._stream_generation += 1
        needs_display: bool = False
        if self._pending_stream_up is not None:
            self._pending_stream_up.cancel()
            self._pending_stream_up = None
            needs_display = True
        if self.online:
            old_stream = self._stream
            self._set_stream(None)
            self._twitch.on_channel_update(self, old_stream, self._stream)
            needs_display = False  # calling on_channel_update always does a display at the end
        if needs_display:
            self.display()

    # async def _send_watch_playlist(self) -> bool:
    async def send_watch(self) -> bool:
        """
        This performs a HEAD request on the stream's current playlist,
        to simulate watching the stream.
        Optimally, send every ~20 seconds to advance drops.
        """
        if self._stream is None:
            return False
        # get the stream url
        try:
            stream_url = await self._stream.get_stream_url()
        except RequestException as exc:
            # A transient GQL/token failure must not kill the critical watch loop.
            logger.warning(f"Stream URL request failed for {self.name}: {exc}")
            return False
        if stream_url is None:
            return False
        # fetch a list of chunks available to download for the stream
        # NOTE: the CDN is configured to forcibly disconnect shortly after serving the list,
        # if we don't do it yourselves. Lets help it by actually doing it ourselves instead.
        try:
            async with self._twitch.request(
                "GET", stream_url, headers={"Connection": "close"}
            ) as chunks_response:
                if chunks_response.status >= 400:
                    # if the stream goes OFFLINE, trying to get a list of chunks returns a 404
                    return False
                available_chunks: str = await chunks_response.text()
        except RequestException:
            return False
        # the response may contain some invalid JSON with duplicate double quotes
        # in the value strings: we need to get rid of them by removing the "url" key entirely
        # if no JSON can be found within the response, this is a NOOP
        available_chunks = re.sub(r'"url": ?".+}",', '', available_chunks)
        # try to decode the suspected JSON
        try:
            available_json: JsonType = json.loads(available_chunks)
        except json.JSONDecodeError:
            # No JSON: this is the expected path. Do nothing and continue with the below.
            pass
        else:
            # JSON was decoded - if there's an error, log it and report failure
            if isinstance(available_json, list):
                available_json = available_json[0]
            if "error" in available_json:
                logger.error(f"Send watch error: \"{available_json['error']}\"")
            return False
        # the list contains ~15 chunks of the stream at ~2s intervals
        chunks_list: list[URLType] = [
            URLType(chunk)
            for chunk in available_chunks.strip().split("\n")
            if chunk.startswith("http")
        ]
        for stream_chunk_url in chunks_list:
            # sending a HEAD request is enough to advance the drops,
            # without downloading the actual stream data
            try:
                async with self._twitch.request(
                    "HEAD", stream_chunk_url
                ) as head_response:
                    if head_response.status != 200:
                        return False
            except RequestException:
                return False
        return True

    async def _send_watch_spade(self) -> bool:
        if self._stream is None:
            return False
        if self._spade_url is None:
            self._spade_url = await self.get_spade_url()
        try:
            async with self._twitch.request(
                "POST", self._spade_url, data=self._stream.spade_payload
            ) as response:
                return response.status == 204
        except RequestException:
            return False

    # NOTE: This is currently unused.
    async def _send_watch_gql(self) -> bool:
        if self._stream is None:
            return False
        try:
            watch_response = await self._twitch.gql_request(self._stream.gql_payload)
            return watch_response["data"]["sendSpadeEvents"]["statusCode"] == 204
        except RequestException:
            return False
