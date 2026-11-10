from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import io
import json
import logging
from functools import partial
from typing import Dict, TypedDict, NewType, TYPE_CHECKING

from utils import json_load, json_save, redact_url
from constants import URLType, CACHE_PATH, CACHE_DB

from PIL import Image as Image_module
from PIL.ImageTk import PhotoImage


logger = logging.getLogger("TwitchDrops.cache")


if TYPE_CHECKING:
    from gui import GUIManager
    from PIL.Image import Image
    from typing_extensions import TypeAlias


ImageHash = NewType("ImageHash", str)
ImageSize: TypeAlias = "tuple[int, int]"


class ExpiringHash(TypedDict):
    hash: ImageHash
    expires: datetime


Hashes = Dict[URLType, ExpiringHash]
default_database: Hashes = {}


class ImageCache:
    LIFETIME = timedelta(days=7)
    # Network fetches are the expensive part. Cache hits don't use this limit.
    # 8 keeps the CDN load reasonable while still being much faster than the old
    # fully-serialized behaviour.
    NETWORK_CONCURRENCY = 8

    def __init__(self, manager: GUIManager) -> None:
        self._root = manager._root
        self._twitch = manager._twitch
        cleanup: bool = False
        CACHE_PATH.mkdir(parents=True, exist_ok=True)
        try:
            self._hashes: Hashes = json_load(CACHE_DB, default_database, merge=False)
        except json.JSONDecodeError:
            # if we can't load the mapping file, delete all existing files,
            # then reinitialize the image cache anew
            cleanup = True
            self._hashes = default_database.copy()
        self._images: dict[ImageHash, Image] = {}
        self._photos: dict[tuple[ImageHash, ImageSize], PhotoImage] = {}
        self._lock = asyncio.Lock()
        # Single-flight per URL: concurrent requests for the same image wait on
        # one download instead of all hitting the CDN.
        self._inflight: dict[URLType, asyncio.Task[tuple[ImageHash, Image]]] = {}
        self._fetch_sem = asyncio.Semaphore(self.NETWORK_CONCURRENCY)
        self._altered: bool = False
        # Set during shutdown. A late GUI event must not start a download against
        # a session that is about to close.
        self._closed: bool = False
        # cleanup the URLs
        hash_counts: dict[ImageHash, int] = {}
        now = datetime.now(timezone.utc)
        for url, hash_dict in list(self._hashes.items()):
            img_hash = hash_dict["hash"]
            if img_hash not in hash_counts:
                hash_counts[img_hash] = 0
            if now >= hash_dict["expires"]:
                del self._hashes[url]
                self._altered = True
            else:
                hash_counts[img_hash] += 1
        for img_hash, count in hash_counts.items():
            if count == 0:
                # hashes come with an extension already
                CACHE_PATH.joinpath(img_hash).unlink(missing_ok=True)
                # NOTE: The hashes are deleted from self._hashes above
        if cleanup:
            # This cleanups the cache folder from unused PNG files
            orphans = [
                file.name for file in CACHE_PATH.glob("*.png") if file.name not in hash_counts
            ]
            for filename in orphans:
                CACHE_PATH.joinpath(filename).unlink(missing_ok=True)

    def save(self, *, force: bool = False) -> None:
        if self._altered or force:
            json_save(CACHE_DB, self._hashes, sort=True)

    async def stop(self) -> None:
        """Cancel and await in-flight image downloads before the session closes."""
        if self._closed:
            return
        self._closed = True
        tasks = list(self._inflight.values())
        self._inflight.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _new_expires(self) -> datetime:
        return datetime.now(timezone.utc) + self.LIFETIME

    def _hash(self, image: Image) -> ImageHash:
        gray = image.resize((10, 10), Image_module.Resampling.LANCZOS).convert('L')
        # Pillow 14 deprecates getdata(); use the flattened API when available.
        data = (
            gray.get_flattened_data()
            if hasattr(gray, "get_flattened_data")
            else gray.getdata()
        )
        pixel_data = list(data)
        avg_pixel = sum(pixel_data) / len(pixel_data)
        bits = ''.join('1' if px >= avg_pixel else '0' for px in pixel_data)
        return ImageHash(f"{int(bits, 2):x}.png")

    def _load_cached_locked(self, url: URLType) -> tuple[ImageHash, Image] | None:
        """
        Resolve a cached URL to an image.

        The caller must hold `self._lock`. This may touch the disk, so it only
        happens on a cache hit; network fetches stay outside the lock.
        """
        hash_dict = self._hashes.get(url)
        if hash_dict is None:
            return None
        img_hash = hash_dict["hash"]
        hash_dict["expires"] = self._new_expires()
        self._altered = True
        image = self._images.get(img_hash)
        if image is not None:
            return img_hash, image
        try:
            loaded = Image_module.open(CACHE_PATH / img_hash)
            loaded.load()  # force full decode so broken data is caught here
        except (FileNotFoundError, Image_module.UnidentifiedImageError, OSError):
            return None
        self._images[img_hash] = loaded
        return img_hash, loaded

    async def _fetch_image(self, url: URLType) -> Image:
        """
        Download and decode an image, falling back to a blank placeholder.

        The semaphore limits concurrent CDN requests. It does not cover cache
        hits, so loading a warm cache stays fast.
        """
        try:
            async with self._fetch_sem:
                async with self._twitch.request("GET", url) as response:
                    if response.status < 400:
                        return Image_module.open(io.BytesIO(await response.read()))
        except Exception:
            pass
        # use a blank white image as a fallback
        return Image_module.new("RGB", (10, 10), (255, 255, 255))

    async def _fetch_and_store(self, url: URLType) -> tuple[ImageHash, Image]:
        # Re-check the cache: another task may have filled it between the caller's
        # lookup and this task starting.
        async with self._lock:
            cached = self._load_cached_locked(url)
        if cached is not None:
            return cached
        image = await self._fetch_image(url)
        img_hash = self._hash(image)
        async with self._lock:
            self._images.setdefault(img_hash, image)
            file_path = CACHE_PATH / img_hash
            if not file_path.exists():
                image.save(file_path)
            self._hashes[url] = {
                "hash": img_hash,
                "expires": self._new_expires()
            }
            self._altered = True
        return img_hash, image

    def _fetch_done(
        self, url: URLType, task: asyncio.Task[tuple[ImageHash, Image]]
    ) -> None:
        if self._inflight.get(url) is task:
            self._inflight.pop(url, None)
        if not task.cancelled() and (exc := task.exception()) is not None:
            logger.warning("Image download failed for %s: %s", redact_url(url), exc)

    async def get(self, url: URLType, size: ImageSize | None = None) -> PhotoImage:
        if self._closed:
            # Shutdown is in progress; never touch the network or the cache file.
            if size is None:
                size = (10, 10)
            return PhotoImage(
                master=self._root,
                image=Image_module.new("RGB", size, (255, 255, 255)),
            )
        # Fast path: cached mapping + memory/disk image, under the metadata lock.
        async with self._lock:
            cached = self._load_cached_locked(url)
        if cached is not None:
            img_hash, image = cached
        else:
            # Single-flight: one task downloads a URL, everyone else waits on it.
            # `shield` is important: a campaign-detail selection change cancels the
            # caller, but must not cancel a download another selection still needs.
            task = self._inflight.get(url)
            if task is None:
                task = asyncio.create_task(self._fetch_and_store(url))
                self._inflight[url] = task
                task.add_done_callback(partial(self._fetch_done, url))
            img_hash, image = await asyncio.shield(task)
        # NOTE: There is deliberately no await in the block below. PhotoImage
        # creation is a Tk-thread operation and this makes the check-and-insert
        # atomic with respect to other coroutines.
        if size is None:
            size = image.size
        photo_key = (img_hash, size)
        if (photo := self._photos.get(photo_key)) is not None:
            return photo
        if image.size != size:
            try:
                image = image.resize(size, Image_module.Resampling.LANCZOS)
            except OSError:
                # broken image data surfaced during resize; fall back to blank placeholder
                image = Image_module.new("RGB", size, (255, 255, 255))
        self._photos[photo_key] = photo = PhotoImage(master=self._root, image=image)
        return photo
