from __future__ import annotations

import asyncio
from contextlib import suppress

from channel import Channel, ChannelStatus
from exceptions import GQLException


class FakeGUIChannels:
    def __init__(self) -> None:
        self.displayed = []
        self.removed = []

    def display(self, channel, *, add: bool = False) -> None:
        self.displayed.append((channel, add))

    def remove(self, channel) -> None:
        self.removed.append(channel)


class FakeGUI:
    def __init__(self) -> None:
        self.channels = FakeGUIChannels()


class FakeSettings:
    available_drops_check = False


class FakeTwitch:
    def __init__(self) -> None:
        self.gui = FakeGUI()
        self.settings = FakeSettings()
        self._campaigns = {}
        self.channel_updates = []

    def on_channel_update(self, channel, stream_before, stream_after) -> None:
        self.channel_updates.append((channel, stream_before, stream_after))

    async def gql_request(self, *args, **kwargs):
        raise AssertionError("gql_request should not be called by these tests")


def make_channel() -> Channel:
    return Channel(FakeTwitch(), id=1, login="tester", display_name="Tester")


def online_payload() -> dict:
    return {
        "stream": {"id": 12345, "viewersCount": 42},
        "broadcastSettings": {
            "game": {"id": 10, "name": "game", "displayName": "Game"},
            "title": "A stream",
        },
    }


def test_initial_status_is_offline() -> None:
    channel = make_channel()
    assert channel.status is ChannelStatus.OFFLINE
    assert channel.offline is True
    assert channel.online is False
    assert channel.pending_online is False


def test_status_since_is_recorded() -> None:
    channel = make_channel()
    before = channel.status_since
    channel.external_update(online_payload(), [])
    assert channel.status is ChannelStatus.ONLINE
    assert channel.status_since >= before


def test_external_update_can_go_online_and_offline() -> None:
    channel = make_channel()
    channel.external_update(online_payload(), [])
    assert channel.online is True
    assert channel.game is not None
    assert channel.game.name == "Game"
    assert channel.viewers == 42
    assert channel.drops_enabled is True

    channel.external_update({"stream": None}, [])
    assert channel.status is ChannelStatus.OFFLINE
    assert channel.game is None
    assert channel.viewers is None


def test_check_online_is_a_debounced_pending_state() -> None:
    async def scenario() -> None:
        channel = make_channel()
        channel.check_online()
        task = channel._pending_stream_up
        assert task is not None
        assert channel.status is ChannelStatus.PENDING_ONLINE

        # A second event while a check is already scheduled must not replace it.
        channel.check_online()
        assert channel._pending_stream_up is task

        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_set_offline_cancels_pending_check() -> None:
    async def scenario() -> None:
        channel = make_channel()
        channel.check_online()
        task = channel._pending_stream_up
        assert task is not None

        channel.set_offline()
        assert channel._pending_stream_up is None
        assert channel.status is ChannelStatus.OFFLINE

        with suppress(asyncio.CancelledError):
            await task
        assert task.cancelled()

    asyncio.run(scenario())


def test_external_update_cancels_pending_check() -> None:
    async def scenario() -> None:
        channel = make_channel()
        channel.check_online()
        task = channel._pending_stream_up
        assert task is not None

        channel.external_update(online_payload(), [])
        assert channel._pending_stream_up is None
        assert channel.online is True

        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_stale_stream_check_cannot_resurrect_an_offline_channel(monkeypatch) -> None:
    async def scenario() -> None:
        channel = make_channel()
        started = asyncio.Event()
        release = asyncio.Event()
        stale_stream = object()

        async def slow_get_stream(self):
            started.set()
            await release.wait()
            return stale_stream

        monkeypatch.setattr(Channel, "get_stream", slow_get_stream)
        generation = channel._stream_generation
        update = asyncio.create_task(channel.update_stream(generation=generation))
        await started.wait()

        # The channel goes offline while the check is in flight.
        channel.set_offline()
        release.set()

        assert await update is False
        assert channel.status is ChannelStatus.OFFLINE
        assert channel._stream is None

    asyncio.run(scenario())


def test_current_generation_is_applied(monkeypatch) -> None:
    async def scenario() -> None:
        channel = make_channel()
        stream = object()

        async def get_stream(self):
            return stream

        monkeypatch.setattr(Channel, "get_stream", get_stream)
        assert await channel.update_stream(generation=channel._stream_generation) is True
        assert channel._stream is stream
        assert channel.online is True

    asyncio.run(scenario())


def test_send_watch_survives_transient_gql_error() -> None:
    async def scenario() -> None:
        channel = make_channel()

        class FailingStream:
            async def get_stream_url(self):
                raise GQLException("service timeout")

        channel._stream = FailingStream()  # type: ignore[assignment]
        assert await channel.send_watch() is False

    asyncio.run(scenario())
