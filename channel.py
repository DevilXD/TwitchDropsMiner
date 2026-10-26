from __future__ import annotations

import re
import gzip
import json
import asyncio
import logging
from base64 import b64decode, b64encode
from typing import Any, SupportsInt, TYPE_CHECKING

import aiohttp
from datetime import datetime, timezone, timedelta
from yarl import URL

from utils import Game, json_minify, isonow, task_wrapper
from exceptions import MinerException, RequestException, GQLException
from constants import CALL, GQL_QUERIES, ONLINE_DELAY, URLType, GQLQuery

if TYPE_CHECKING:
    from twitch import Twitch
    from gui import ChannelList
    from constants import JsonType, GQLPersistedQuery


logger = logging.getLogger("TwitchDrops")

# Twitch ignores or rejects Android TV (SMARTBOX) user agents for the public
# website and watch/spade endpoints. Always use a modern desktop Chrome UA for
# channel page fetches and watch payloads so minute-watched events are counted.
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


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
        self._ingest_url: URLType | None = None

    @property
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

    @property
    def spade_payload(self) -> JsonType:
        return {
            "data": (b64encode(json_minify(self._watch_payload).encode("utf8"))).decode("utf8")
        }

    @property
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
        settings = channel_data.get("broadcastSettings") or {}
        return cls(
            channel,
            id=stream["id"],
            game=settings.get("game"),
            viewers=stream.get("viewersCount", 0),
            title=settings.get("title") or "",
        )

    @classmethod
    def from_directory(
        cls, channel: Channel, channel_data: JsonType, *, drops_enabled: bool = False
    ) -> Stream:
        self = cls(
            channel,
            id=channel_data["id"],
            game=channel_data.get("game"),
            viewers=channel_data.get("viewersCount", 0),
            title=channel_data.get("title") or "",
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
        try:
            # get the stream playback access token from GQL
            playback_token_response: JsonType = await self.channel._twitch.gql_request(
                GQL_QUERIES["PlaybackAccessToken"].with_variables({"login": self.channel._login})
            )
            token_data: JsonType | None = (
                (playback_token_response.get("data") or {}).get("streamPlaybackAccessToken")
            )
            if not isinstance(token_data, dict):
                return None
            token_value = token_data.get("value")
            token_signature = token_data.get("signature")
            if not token_value or not token_signature:
                return None
        except (GQLException, MinerException, aiohttp.ClientError, asyncio.TimeoutError):
            return None
        # using the token, query Twitch for a list of all available stream qualities
        available_qualities: str = ''
        try:
            async with self.channel._twitch.request(
                "GET",
                URL(
                    "https://usher.ttvnw.net/api/channel/hls/"
                    f"{self.channel._login}.m3u8?sig={token_signature}&token={token_value}"
                ),
                headers={"User-Agent": DESKTOP_USER_AGENT},
            ) as qualities_response:
                if qualities_response.status >= 400:
                    return None
                available_qualities = await qualities_response.text()
            # try to decode the suspected JSON
            try:
                available_json: JsonType | list[JsonType] = json.loads(available_qualities)
            except json.JSONDecodeError:
                # No JSON: this is the expected path. Do nothing and continue with the below.
                pass
            else:
                # JSON was decoded - if there's an error, log it and report failure
                if isinstance(available_json, list):
                    available_json = available_json[0] if available_json else {}
                if isinstance(available_json, dict) and "error" in available_json:
                    logger.error(f"Stream URL get error: \"{available_json['error']}\"")
                    self.channel.set_offline()
                return None
            # Extract per-session HLS ingest Spade URL if embedded in #EXT-X-TWITCH-INFO (C="...")
            ingest_match = re.search(r',C="([^"]+)"', available_qualities)
            if ingest_match:
                try:
                    raw_ingest = ingest_match.group(1)
                    raw_ingest += "=" * (-len(raw_ingest) % 4)
                    decoded_ingest = b64decode(raw_ingest).decode("utf8", errors="ignore")
                    if decoded_ingest.startswith("http"):
                        self._ingest_url = URLType(decoded_ingest)
                except ValueError:
                    pass
            # pick the last URL from the list, usually with the lowest quality stream
            http_lines = [
                line.strip()
                for line in available_qualities.strip().splitlines()
                if line.strip().startswith("http")
            ]
            if not http_lines:
                return None
            self._stream_url = URLType(http_lines[-1])
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, MinerException):
            return None
        return self._stream_url


class Channel:
    __slots__ = (
        "_twitch", "_gui_channels", "id", "_login", "_display_name", "_spade_url",
        "_stream", "_pending_stream_up", "acl_based"
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
        # Channel HTML is always fetched from the normal Twitch website. SMARTBOX
        # authentication is only an API identity; android.tv.twitch.tv channel pages
        # do not expose the settings/spade metadata needed for watch tracking.
        return URLType(f"https://www.twitch.tv/{self._login}")

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

    @property
    def is_current_acl(self) -> bool:
        """
        True if this channel is an allowed channel for an active earnable campaign
        matching the game it is currently streaming (or an active earnable campaign if offline).
        """
        if not self.acl_based:
            return False
        if self._stream is not None and self._stream.game is not None:
            current_game = self._stream.game
            return any(
                campaign.game == current_game and self in campaign.allowed_channels
                and campaign.can_earn(self, ignore_channel_status=True)
                for campaign in self._twitch.inventory
            )
        now_utc = datetime.now(timezone.utc)
        return any(
            self in campaign.allowed_channels
            and campaign.can_earn_within(now_utc + timedelta(hours=1))
            for campaign in self._twitch.inventory
        )

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
        try:
            SETTINGS_PATTERN: str = r'src="(https://[\w.]+/config/settings\.[0-9a-f]{32}\.js)"'
            SPADE_PATTERN: str = r'"spade_?url": ?"(https://[.\w\-/]+)"'
            headers = {"User-Agent": DESKTOP_USER_AGENT}
            async with self._twitch.request("GET", self.url, headers=headers) as response1:
                streamer_html: str = await response1.text(encoding="utf8", errors="replace")
            match = re.search(SPADE_PATTERN, streamer_html, re.I)
            if not match:
                match = re.search(SETTINGS_PATTERN, streamer_html, re.I)
                if match:
                    streamer_settings = match.group(1)
                    async with self._twitch.request(
                        "GET", streamer_settings, headers=headers
                    ) as response2:
                        settings_js: str = await response2.text(encoding="utf8", errors="replace")
                    match = re.search(SPADE_PATTERN, settings_js, re.I)
            if match:
                return URLType(match.group(1))
        except (MinerException, RequestException, aiohttp.ClientError, asyncio.TimeoutError, Exception) as exc:
            logger.log(CALL, f"Spade URL extraction encountered an error for {self.name}: {exc}")
        return URLType("https://spade.twitch.tv/")

    def _check_drops_enabled(
        self, available_drops: list[JsonType], stream: Stream | None = None
    ) -> bool:
        if any(
            (
                isinstance(campaign_data, dict)
                and "id" in campaign_data
                and (campaign := self._twitch._campaigns.get(campaign_data["id"])) is not None
                and campaign.can_earn(self, ignore_channel_status=True)
            )
            for campaign_data in available_drops
        ):
            return True

        # Fallback: if available_drops is empty or GQL returned null/no matching campaigns,
        # do not falsely mark drops_enabled = False if this channel is an ACL channel for
        # an active earnable campaign, OR matches an active non-ACL campaign for stream.game.
        target_stream = stream if stream is not None else self._stream
        if target_stream is not None and target_stream.game is not None:
            game = target_stream.game
            for campaign in self._twitch.inventory:
                if campaign.game == game and (not campaign.allowed_channels or self in campaign.allowed_channels):
                    if campaign.can_earn(self, ignore_channel_status=True):
                        return True

        return False

    def update_available_drops(self, available_drops: list[JsonType]) -> None:
        if self._stream is not None:
            self._stream.drops_enabled = self._check_drops_enabled(available_drops, stream=self._stream)

    def external_update(self, channel_data: JsonType, available_drops: list[JsonType]):
        """
        Update stream information based on data provided externally.

        Used for bulk-updates of channel statuses during reload.
        """
        if not channel_data.get("stream"):
            self._stream = None
            return
        stream = Stream.from_get_stream(self, channel_data)
        if not stream.drops_enabled:
            stream.drops_enabled = self._check_drops_enabled(available_drops, stream=stream)
        self._stream = stream

    async def get_stream(self) -> Stream | None:
        try:
            response: JsonType = await self._twitch.gql_request(self.stream_gql)
        except MinerException as exc:
            raise MinerException(f"Channel: {self._login}") from exc
        channel_data: JsonType | None = (response.get("data") or {}).get("user")
        if not isinstance(channel_data, dict):
            return None
        # fill in display name
        if self._display_name is None:
            self._display_name = channel_data.get("displayName")
        if not channel_data.get("stream"):
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
                channel_node: JsonType | None = (
                    (available_drops_campaigns.get("data") or {}).get("channel")
                )
                if isinstance(channel_node, dict):
                    stream.drops_enabled = self._check_drops_enabled(
                        channel_node.get("viewerDropCampaigns") or [],
                        stream=stream,
                    )
            if not stream.drops_enabled:
                stream.drops_enabled = self._check_drops_enabled([], stream=stream)
        return stream

    async def update_stream(self) -> bool:
        """
        Fetches the current channel stream, and if one exists,
        updates it's game, title, tags and viewers. Updates channel status in general.
        """
        old_stream = self._stream
        self._stream = await self.get_stream()
        self._twitch.on_channel_update(self, old_stream, self._stream)
        return self._stream is not None

    @task_wrapper
    async def _online_delay(self) -> None:
        """
        The 'stream-up' event is sent before the stream actually goes online,
        so just wait a bit and check if it's actually online by then.
        """
        try:
            await asyncio.sleep(ONLINE_DELAY.total_seconds())
            self._pending_stream_up = None  # for 'display' to work properly
            await self.update_stream()
        except (MinerException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning(f"Delayed stream update failed for {self.name}: {exc}")
            self.display()
        finally:
            self._pending_stream_up = None

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
        if self._pending_stream_up is None or self._pending_stream_up.done():
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
            self._twitch.on_channel_update(self, old_stream, self._stream)
            needs_display = False  # calling on_channel_update always does a display at the end
        if needs_display:
            self.display()

    async def _send_watch_hls(self) -> bool:
        """
        Perform a HEAD request on the stream's latest HLS segment to advance drops.
        """
        if self._stream is None:
            return False
        stream_url = await self._stream.get_stream_url()
        if stream_url is None:
            return False
        try:
            # fetch a list of chunks available to download for the stream
            # NOTE: the CDN is configured to forcibly disconnect shortly after serving the list,
            # if we don't do it yourselves. Lets help it by actually doing it ourselves instead.
            async with self._twitch.request(
                "GET",
                stream_url,
                headers={"Connection": "close", "User-Agent": DESKTOP_USER_AGENT},
            ) as chunks_response:
                if chunks_response.status >= 400:
                    # stream went OFFLINE or playback token expired; invalidate cached URL
                    if self._stream is not None:
                        self._stream._stream_url = None
                        self._stream._ingest_url = None
                    return False
                available_chunks: str = await chunks_response.text()
        except (MinerException, aiohttp.ClientError, asyncio.TimeoutError):
            if self._stream is not None:
                self._stream._stream_url = None
                self._stream._ingest_url = None
            return False
        # the response may contain some invalid JSON with duplicate double quotes
        # in the value strings: we need to get rid of them by removing the "url" key entirely
        # if no JSON can be found within the response, this is a NOOP
        available_chunks = re.sub(r'"url": ?".+}",', '', available_chunks)
        # try to decode the suspected JSON
        try:
            available_json: JsonType | list[JsonType] = json.loads(available_chunks)
        except json.JSONDecodeError:
            # No JSON: this is the expected path. Do nothing and continue with the below.
            pass
        else:
            # JSON was decoded - if there's an error, log it and report failure
            if isinstance(available_json, list):
                available_json = available_json[0] if available_json else {}
            if isinstance(available_json, dict) and "error" in available_json:
                logger.error(f"Send watch error: \"{available_json['error']}\"")
            return False
        # the list contains ~15 chunks of the stream at ~2s intervals
        chunks_list: list[URLType] = [
            URLType(chunk.strip())
            for chunk in available_chunks.strip().splitlines()
            if chunk.strip().startswith("http")
        ]
        if not chunks_list:
            return False
        success_count = 0
        consecutive_failures = 0
        for stream_chunk_url in chunks_list:
            try:
                async with self._twitch.request(
                    "HEAD", stream_chunk_url, headers={"User-Agent": DESKTOP_USER_AGENT}
                ) as head_response:
                    if head_response.status == 200:
                        success_count += 1
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
            except (MinerException, aiohttp.ClientError, asyncio.TimeoutError):
                consecutive_failures += 1
            if consecutive_failures >= 3:
                break
        head_ok = success_count >= max(1, len(chunks_list) // 2)
        # Also post the minute-watched payload to the per-session HLS ingest URL if available
        if self._stream is not None and self._stream._ingest_url is not None:
            try:
                async with self._twitch.request(
                    "POST",
                    self._stream._ingest_url,
                    data=self._stream.spade_payload,
                    headers={"User-Agent": DESKTOP_USER_AGENT},
                ) as ingest_response:
                    if ingest_response.status in (200, 204):
                        head_ok = True
            except (MinerException, aiohttp.ClientError, asyncio.TimeoutError):
                pass
        return head_ok

    async def send_watch(self) -> bool:
        """
        Send the Spade beacon as the primary watch mechanism (required under SMARTBOX),
        while also triggering GQL and HLS checks concurrently.
        """
        if self._stream is None:
            return False
        spade_ok, gql_ok, hls_ok = await asyncio.gather(
            self._send_watch_spade(),
            self._send_watch_gql(),
            self._send_watch_hls(),
            return_exceptions=True,
        )
        return bool(spade_ok is True or gql_ok is True or hls_ok is True)

    async def _send_watch_spade(self) -> bool:
        if self._stream is None:
            return False
        if self._spade_url is None:
            try:
                self._spade_url = await self.get_spade_url()
            except Exception:
                self._spade_url = URLType("https://spade.twitch.tv/")
        target_url = self._spade_url or URLType("https://spade.twitch.tv/")
        try:
            async with self._twitch.request(
                "POST",
                target_url,
                data=self._stream.spade_payload,
                headers={"User-Agent": DESKTOP_USER_AGENT},
            ) as response:
                if response.status not in (200, 204):
                    logger.log(
                        CALL,
                        f"Spade watch payload rejected for {self.name}: HTTP {response.status}",
                    )
                    self._spade_url = None
                    return False
                return True
        except (MinerException, aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def _send_watch_gql(self) -> bool:
        if self._stream is None:
            return False
        try:
            watch_response = await self._twitch.gql_request(self._stream.gql_payload)
            if not isinstance(watch_response, dict):
                return False
            data = watch_response.get("data")
            if not isinstance(data, dict):
                return False
            events = data.get("sendSpadeEvents")
            if isinstance(events, dict) and events.get("statusCode") == 204:
                return True
            return False
        except (MinerException, RequestException, GQLException, aiohttp.ClientError, asyncio.TimeoutError):
            return False
