from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import io
import json
from typing import Dict, TypedDict, NewType, TYPE_CHECKING

from utils import json_load, json_save
from constants import URLType, CACHE_PATH, CACHE_DB

from PIL import Image as Image_module
from PIL.ImageTk import PhotoImage


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
        self._altered: bool = False
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

    def _new_expires(self) -> datetime:
        return datetime.now(timezone.utc) + self.LIFETIME

    def _hash(self, image: Image) -> ImageHash:
        pixel_data = list(
            image.resize((10, 10), Image_module.Resampling.LANCZOS).convert('L').getdata()
        )
        avg_pixel = sum(pixel_data) / len(pixel_data)
        bits = ''.join('1' if px >= avg_pixel else '0' for px in pixel_data)
        return ImageHash(f"{int(bits, 2):x}.png")

    async def get(self, url: URLType, size: ImageSize | None = None) -> PhotoImage:
        async with self._lock:
            image: Image | None = None
            if url in self._hashes:
                img_hash = self._hashes[url]["hash"]
                self._hashes[url]["expires"] = self._new_expires()
                if img_hash in self._images:
                    image = self._images[img_hash]
                else:
                    try:
                        self._images[img_hash] = image = Image_module.open(CACHE_PATH / img_hash)
                    except (FileNotFoundError, Image_module.UnidentifiedImageError):
                        pass
            if image is None:
                try:
                    async with self._twitch.request("GET", url) as response:
                        if response.status != 404:
                            image = Image_module.open(io.BytesIO(await response.read()))
                except Exception:
                    pass
                if image is None:
                    # use a blank white image as a fallback
                    image = Image_module.new("RGB", (10, 10), (255, 255, 255))
                img_hash = self._hash(image)
                self._images[img_hash] = image
                image.save(CACHE_PATH / img_hash)
                self._hashes[url] = {
                    "hash": img_hash,
                    "expires": self._new_expires()
                }
        # NOTE: If self._hashes ever stops being updated in both above if cases,
        # this will need to be moved
        self._altered = True
        if size is None:
            size = image.size
        photo_key = (img_hash, size)
        if photo_key in self._photos:
            return self._photos[photo_key]
        if image.size != size:
            image = image.resize(size, Image_module.Palette.ADAPTIVE)
        self._photos[photo_key] = photo = PhotoImage(master=self._root, image=image)
        return photo
