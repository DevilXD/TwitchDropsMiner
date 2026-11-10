from __future__ import annotations

import asyncio
import io
from contextlib import suppress
from types import SimpleNamespace

import pytest
from PIL import Image as Image_module

import cache as cache_module
from cache import ImageCache


def red_png() -> bytes:
    buffer = io.BytesIO()
    Image_module.new("RGB", (40, 60), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, owner: "FakeTwitch", status: int) -> None:
        self._owner = owner
        self.status = status

    async def __aenter__(self):
        self._owner.active += 1
        self._owner.max_active = max(self._owner.max_active, self._owner.active)
        await asyncio.sleep(self._owner.delay)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._owner.active -= 1
        return False

    async def read(self) -> bytes:
        return self._owner.data


class FakeTwitch:
    def __init__(self, data: bytes, *, status: int = 200) -> None:
        self.data = data
        self.status = status
        self.calls: dict[str, int] = {}
        self.active = 0
        self.max_active = 0
        self.delay = 0.0

    def request(self, method: str, url: str):
        self.calls[url] = self.calls.get(url, 0) + 1
        return FakeResponse(self, self.status)


class FakePhoto:
    def __init__(self, master=None, image=None) -> None:
        self.master = master
        self.image = image


@pytest.fixture
def cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache_module, "CACHE_PATH", tmp_path)
    monkeypatch.setattr(cache_module, "CACHE_DB", tmp_path / "mapping.json")
    monkeypatch.setattr(cache_module, "PhotoImage", FakePhoto)
    twitch = FakeTwitch(red_png())
    manager = SimpleNamespace(_root=None, _twitch=twitch)
    return ImageCache(manager), twitch


def test_concurrent_same_url_is_fetched_once(cache) -> None:
    image_cache, twitch = cache
    url = "https://example.com/art.png"

    async def scenario():
        photos = await asyncio.gather(
            *(image_cache.get(url, (20, 30)) for _ in range(10))
        )
        assert len({id(photo) for photo in photos}) == 1

    asyncio.run(scenario())
    assert twitch.calls[url] == 1


def test_different_urls_fetch_concurrently(cache) -> None:
    image_cache, twitch = cache
    first = "https://example.com/first.png"
    second = "https://example.com/second.png"
    twitch.delay = 0.05

    async def scenario():
        await asyncio.gather(image_cache.get(first), image_cache.get(second))

    asyncio.run(scenario())
    assert twitch.max_active >= 2, "network fetches must not be serialized"


def test_cache_hit_does_not_refetch(cache) -> None:
    image_cache, twitch = cache
    url = "https://example.com/cached.png"

    async def scenario():
        first = await image_cache.get(url)
        second = await image_cache.get(url)
        assert first is second

    asyncio.run(scenario())
    assert twitch.calls[url] == 1


def test_cancelling_one_waiter_does_not_cancel_shared_fetch(cache) -> None:
    image_cache, twitch = cache
    url = "https://example.com/shared.png"
    twitch.delay = 0.05

    async def scenario():
        first = asyncio.create_task(image_cache.get(url))
        await asyncio.sleep(0.01)  # start the shared fetch
        second = asyncio.create_task(image_cache.get(url))
        first.cancel()
        with suppress(asyncio.CancelledError):
            await first
        photo = await second
        assert photo is not None

    asyncio.run(scenario())
    assert twitch.calls[url] == 1


def test_get_after_stop_returns_placeholder_without_network(cache) -> None:
    image_cache, twitch = cache
    url = "https://example.com/late.png"

    async def scenario():
        await image_cache.stop()
        photo = await image_cache.get(url, (20, 30))
        assert isinstance(photo, FakePhoto)

    asyncio.run(scenario())
    assert url not in twitch.calls


def test_stop_cancels_and_awaits_inflight_download(cache) -> None:
    image_cache, twitch = cache
    twitch.delay = 0.2
    url = "https://example.com/slow.png"

    async def scenario():
        waiter = asyncio.create_task(image_cache.get(url))
        await asyncio.sleep(0.01)  # let the shared fetch start
        await image_cache.stop()
        assert image_cache._inflight == {}
        with suppress(asyncio.CancelledError):
            await waiter

    asyncio.run(scenario())


def test_failed_download_uses_placeholder_and_is_cached(cache, monkeypatch) -> None:
    image_cache, _ = cache
    failing = FakeTwitch(red_png(), status=500)
    image_cache._twitch = failing
    url = "https://example.com/broken.png"

    async def scenario():
        first = await image_cache.get(url)
        second = await image_cache.get(url)
        assert first is second

    asyncio.run(scenario())
    assert failing.calls[url] == 1
