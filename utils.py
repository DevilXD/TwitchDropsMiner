from __future__ import annotations

import io
import os
import re
import sys
import json
import random
import string
import asyncio
import logging
import traceback
import webbrowser
import tkinter as tk
from enum import Enum
from pathlib import Path
from functools import wraps
from contextlib import suppress
from functools import cached_property
from datetime import datetime, timezone
from collections import abc, OrderedDict
from typing import Any, Literal, Callable, Generic, Mapping, TypeVar, ParamSpec, cast

from yarl import URL
from PIL.ImageTk import PhotoImage
from PIL import Image as Image_module

from exceptions import ExitRequest, ReloadRequest
from constants import IS_PACKAGED, JsonType, PriorityMode
from constants import _resource_path as resource_path  # noqa


_T = TypeVar("_T")  # type
_D = TypeVar("_D")  # default
_P = ParamSpec("_P")  # params
_JSON_T = TypeVar("_JSON_T", bound=Mapping[Any, Any])
logger = logging.getLogger("TwitchDrops")


def set_root_icon(root: tk.Tk, image_path: Path | str) -> None:
    with Image_module.open(image_path) as image:
        icon_photo = PhotoImage(master=root, image=image)
    root.iconphoto(True, icon_photo)  # type: ignore[arg-type]
    # keep a reference to the PhotoImage to avoid the ResourceWarning
    root._icon_image = icon_photo  # type: ignore[attr-defined]


async def first_to_complete(coros: abc.Iterable[abc.Coroutine[Any, Any, _T]]) -> _T:
    # In Python 3.11, we need to explicitly wrap awaitables
    tasks = [asyncio.ensure_future(coro) for coro in coros]
    done: set[asyncio.Task[Any]]
    pending: set[asyncio.Task[Any]]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    return await next(iter(done))


def chunk(to_chunk: abc.Iterable[_T], chunk_length: int) -> abc.Generator[list[_T], None, None]:
    list_to_chunk = list(to_chunk)
    for i in range(0, len(list_to_chunk), chunk_length):
        yield list_to_chunk[i:i + chunk_length]


def format_traceback(exc: BaseException, **kwargs: Any) -> str:
    """
    Like `traceback.print_exc` but returns a string. Uses the passed-in exception.
    Any additional `**kwargs` are passed to the underlaying `traceback.format_exception`.
    """
    return ''.join(traceback.format_exception(type(exc), exc, **kwargs))


def lock_file(path: Path) -> tuple[bool, io.TextIOWrapper]:
    file = path.open('w', encoding="utf8")
    file.write('ツ')
    file.flush()
    if sys.platform == "win32":
        import msvcrt
        try:
            # we need to lock at least one byte for this to work
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, max(path.stat().st_size, 1))
        except Exception:
            return False, file
        return True, file
    if sys.platform == "linux":
        import fcntl
        try:
            fcntl.lockf(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            return False, file
        return True, file
    # for unsupported systems, just always return True
    return True, file


def json_minify(data: JsonType | list[JsonType]) -> str:
    """
    Returns minified JSON for payload usage.
    """
    return json.dumps(data, separators=(',', ':'))


def timestamp(string: str) -> datetime:
    try:
        return datetime.strptime(string, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.strptime(string, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


CHARS_ASCII = string.ascii_letters + string.digits
CHARS_HEX_LOWER = string.digits + "abcdef"
CHARS_HEX_UPPER = string.digits + "ABCDEF"


def create_nonce(chars: str, length: int) -> str:
    return ''.join(random.choices(chars, k=length))


def deduplicate(iterable: abc.Iterable[_T]) -> list[_T]:
    return list(OrderedDict.fromkeys(iterable).keys())


def task_wrapper(
    afunc: abc.Callable[_P, abc.Coroutine[Any, Any, _T]] | None = None, *, critical: bool = False
):
    def decorator(
        afunc: abc.Callable[_P, abc.Coroutine[Any, Any, _T]]
    ) -> abc.Callable[_P, abc.Coroutine[Any, Any, _T]]:
        @wraps(afunc)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs):
            try:
                await afunc(*args, **kwargs)
            except (ExitRequest, ReloadRequest):
                pass
            except Exception:
                logger.exception(f"Exception in {afunc.__name__} task")
                if critical:
                    # critical task's death should trigger a termination.
                    # there isn't an easy and sure way to obtain the Twitch instance here,
                    # but we can improvise finding it
                    from twitch import Twitch  # cyclic import
                    probe = args and args[0] or None  # extract from 'self' arg
                    if isinstance(probe, Twitch):
                        probe.close()
                    elif probe is not None:
                        probe = getattr(probe, "_twitch", None)  # extract from '_twitch' attr
                        if isinstance(probe, Twitch):
                            probe.close()
                raise  # raise up to the wrapping task
        return wrapper
    if afunc is None:
        return decorator
    return decorator(afunc)


def invalidate_cache(instance, *attrnames):
    """
    To be used to invalidate `functools.cached_property`.
    """
    for name in attrnames:
        with suppress(AttributeError):
            delattr(instance, name)


def _serialize(obj: Any) -> Any:
    # convert data
    d: int | str | float | list[Any] | JsonType
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            # assume naive objects are UTC
            obj = obj.replace(tzinfo=timezone.utc)
        d = obj.timestamp()
    elif isinstance(obj, set):
        d = list(obj)
    elif isinstance(obj, Enum):
        # NOTE: IntEnum cannot be used, as it will get serialized as a plain integer,
        # then loaded back as an integer as well.
        d = obj.value
    elif isinstance(obj, URL):
        d = str(obj)
    else:
        raise TypeError(obj)
    # store with type
    return {
        "__type": type(obj).__name__,
        "data": d,
    }


_MISSING = object()
SERIALIZE_ENV: dict[str, Callable[[Any], object]] = {
    "set": set,
    "URL": URL,
    "PriorityMode": PriorityMode,
    "datetime": lambda d: datetime.fromtimestamp(d, timezone.utc),
}


def _remove_missing(obj: JsonType) -> JsonType:
    # this modifies obj in place, but we return it just in case
    for key, value in obj.copy().items():
        if value is _MISSING:
            del obj[key]
        elif isinstance(value, dict):
            _remove_missing(value)
            if not value:
                # the dict is empty now, so remove it's key entirely
                del obj[key]
    return obj


def _deserialize(obj: JsonType) -> Any:
    if "__type" in obj:
        obj_type = obj["__type"]
        if obj_type in SERIALIZE_ENV:
            return SERIALIZE_ENV[obj_type](obj["data"])
        else:
            return _MISSING
    return obj


def merge_json(obj: JsonType, template: Mapping[Any, Any]) -> None:
    # NOTE: This modifies object in place
    for k, v in list(obj.items()):
        if k not in template:
            # unknown key: overwrite from template
            del obj[k]
        elif type(v) is not type(template[k]):
            # types don't match: overwrite from template
            obj[k] = template[k]
        elif isinstance(v, dict):
            assert isinstance(template[k], dict)
            merge_json(v, template[k])
    # ensure the object is not missing any keys
    for k in template.keys():
        if k not in obj:
            obj[k] = template[k]


def json_load(path: Path, defaults: _JSON_T, *, merge: bool = True) -> _JSON_T:
    defaults_dict: JsonType = dict(defaults)
    if path.exists():
        with open(path, 'r', encoding="utf8") as file:
            combined: JsonType = _remove_missing(json.load(file, object_hook=_deserialize))
        if merge:
            merge_json(combined, defaults_dict)
    else:
        combined = defaults_dict
    return cast(_JSON_T, combined)


def json_save(path: Path, contents: Mapping[Any, Any], *, sort: bool = False) -> None:
    with open(path, 'w', encoding="utf8") as file:
        json.dump(contents, file, default=_serialize, sort_keys=sort, indent=4)


def webopen(url: URL | str):
    url_str = str(url)
    if IS_PACKAGED and sys.platform == "linux":
        # https://pyinstaller.org/en/stable/
        # runtime-information.html#ld-library-path-libpath-considerations
        # NOTE: All 4 cases need to be handled here: either of the two values can be there or not.
        ld_env = "LD_LIBRARY_PATH"
        ld_path_curr = os.environ.get(ld_env)
        ld_path_orig = os.environ.get(f"{ld_env}_ORIG")
        if ld_path_orig is not None:
            os.environ[ld_env] = ld_path_orig
        elif ld_path_curr is not None:
            # pop current
            os.environ.pop(ld_env)

        webbrowser.open_new_tab(url_str)

        if ld_path_curr is not None:
            os.environ[ld_env] = ld_path_curr
        elif ld_path_orig is not None:
            # pop original
            os.environ.pop(ld_env)
    else:
        webbrowser.open_new_tab(url_str)


class ExponentialBackoff:
    def __init__(
        self,
        *,
        base: float = 2,
        variance: float | tuple[float, float] = 0.1,
        shift: float = 0,
        maximum: float = 300,
    ):
        if base <= 1:
            raise ValueError("Base has to be greater than 1")
        self.steps: int = 0
        self.base: float = float(base)
        self.shift: float = float(shift)
        self.maximum: float = float(maximum)
        self.variance_min: float
        self.variance_max: float
        if isinstance(variance, tuple):
            self.variance_min, self.variance_max = variance
        else:
            self.variance_min = 1 - variance
            self.variance_max = 1 + variance

    @property
    def exp(self) -> int:
        return max(0, self.steps - 1)

    def __iter__(self) -> abc.Iterator[float]:
        return self

    def __next__(self) -> float:
        value: float = (
            pow(self.base, self.steps)
            * random.uniform(self.variance_min, self.variance_max)
            + self.shift
        )
        if value > self.maximum:
            return self.maximum
        # NOTE: variance can cause the returned value to be lower than the previous one already,
        # so this should be safe to move past the first return,
        # to prevent the exponent from getting very big after reaching max and many iterations
        self.steps += 1
        return value

    def reset(self) -> None:
        self.steps = 0


class RateLimiter:
    def __init__(self, *, capacity: int, window: int):
        self.total: int = 0
        self.concurrent: int = 0
        self.window: int = window
        self.capacity: int = capacity
        self._reset_task: asyncio.Task[None] | None = None
        self._cond: asyncio.Condition = asyncio.Condition()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.concurrent}/{self.total}/{self.capacity})"

    def __del__(self) -> None:
        if self._reset_task is not None:
            self._reset_task.cancel()

    def _can_proceed(self) -> bool:
        return max(self.total, self.concurrent) < self.capacity

    async def __aenter__(self):
        async with self._cond:
            await self._cond.wait_for(self._can_proceed)
            self.total += 1
            self.concurrent += 1
            if self._reset_task is None:
                self._reset_task = asyncio.create_task(self._rtask())

    async def __aexit__(self, exc_type, exc, tb):
        self.concurrent -= 1
        async with self._cond:
            self._cond.notify(self.capacity - self.concurrent)

    async def _reset(self) -> None:
        if self._reset_task is not None:
            self._reset_task = None
        async with self._cond:
            self.total = 0
            if self.concurrent < self.capacity:
                self._cond.notify(self.capacity - self.concurrent)

    async def _rtask(self) -> None:
        await asyncio.sleep(self.window)
        await self._reset()


class AwaitableValue(Generic[_T]):
    def __init__(self):
        self._value: _T
        self._event = asyncio.Event()

    def has_value(self) -> bool:
        return self._event.is_set()

    def wait(self) -> abc.Coroutine[Any, Any, Literal[True]]:
        return self._event.wait()

    def get_with_default(self, default: _D) -> _T | _D:
        if self._event.is_set():
            return self._value
        return default

    async def get(self) -> _T:
        await self._event.wait()
        return self._value

    def set(self, value: _T) -> None:
        self._value = value
        self._event.set()

    def clear(self) -> None:
        self._event.clear()


class Game:
    SPECIAL_EVENTS_GAME_ID: int = 509663

    def __init__(self, data: JsonType):
        self.id: int = int(data["id"])
        self.name: str = data.get("displayName") or data["name"]
        if "slug" in data:
            self.slug = data["slug"]

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"Game({self.id}, {self.name})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return self.id

    @cached_property
    def slug(self) -> str:
        """
        Converts the game name into a slug, useable for the GQL API.
        """
        # remove specific characters
        slug_text = re.sub(r'\'', '', self.name.lower())
        # remove non alpha-numeric characters
        slug_text = re.sub(r'\W+', '-', slug_text)
        # strip and collapse dashes
        slug_text = re.sub(r'-{2,}', '-', slug_text.strip('-'))
        return slug_text

    def is_special_events(self) -> bool:
        return self.id == self.SPECIAL_EVENTS_GAME_ID
