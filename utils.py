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
from datetime import datetime, timezone
from collections import abc, OrderedDict
from typing import (
    Any, Literal, MutableSet, Callable, Generic, Mapping, TypeVar, cast, TYPE_CHECKING
)

import yarl
from PIL.ImageTk import PhotoImage
from PIL import Image as Image_module

from constants import JsonType, IS_PACKAGED
from exceptions import ExitRequest, ReloadRequest
from constants import _resource_path as resource_path  # noqa

if TYPE_CHECKING:
    from typing_extensions import ParamSpec
else:
    # stub it
    class ParamSpec:
        def __init__(*args, **kwargs):
            pass


_T = TypeVar("_T")  # type
_D = TypeVar("_D")  # default
_P = ParamSpec("_P")  # params
_JSON_T = TypeVar("_JSON_T", bound=Mapping[Any, Any])
logger = logging.getLogger("TwitchDrops")


def set_root_icon(root: tk.Tk, image_path: Path | str) -> None:
    with Image_module.open(image_path) as image:
        icon_photo = PhotoImage(master=root, image=image)
    root.iconphoto(True, icon_photo)
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
    afunc: abc.Callable[_P, abc.Coroutine[Any, Any, _T]]
) -> abc.Callable[_P, abc.Coroutine[Any, Any, _T]]:
    @wraps(afunc)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs):
        try:
            await afunc(*args, **kwargs)
        except (ExitRequest, ReloadRequest):
            pass
        except Exception:
            logger.exception("Exception in task")
            raise  # raise up to the wrapping task
    return wrapper


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
    if isinstance(obj, set):
        d = list(obj)
    elif isinstance(obj, Enum):
        d = obj.value
    elif isinstance(obj, datetime):
        if obj.tzinfo is None:
            # assume naive objects are UTC
            obj = obj.replace(tzinfo=timezone.utc)
        d = obj.timestamp()
    elif isinstance(obj, yarl.URL):
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
    "datetime": lambda d: datetime.fromtimestamp(d, timezone.utc),
    "URL": yarl.URL,
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
            del obj[k]
        elif isinstance(v, dict):
            if isinstance(template[k], dict):
                merge_json(v, template[k])
            else:
                # object is a dict, template is not: overwrite from template
                obj[k] = template[k]
        elif isinstance(template[k], dict):
            # template is a dict, object is not: overwrite from template
            obj[k] = template[k]
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


def webopen(url: str):
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

        webbrowser.open_new_tab(url)

        if ld_path_curr is not None:
            os.environ[ld_env] = ld_path_curr
        elif ld_path_orig is not None:
            # pop original
            os.environ.pop(ld_env)
    else:
        webbrowser.open_new_tab(url)


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


class OrderedSet(MutableSet[_T]):
    """
    Implementation of a set that preserves insertion order,
    based on OrderedDict with values set to None.
    """
    def __init__(self, iterable: abc.Iterable[_T] = [], /):
        self._items: OrderedDict[_T, None] = OrderedDict((item, None) for item in iterable)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}([{', '.join(map(repr, self._items))}])"

    def __contains__(self, item: object, /) -> bool:
        return item in self._items

    def __iter__(self) -> abc.Iterator[_T]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def add(self, item: _T, /) -> None:
        self._items[item] = None

    def discard(self, item: _T, /) -> None:
        with suppress(KeyError):
            del self._items[item]

    def update(self, *others: abc.Iterable[_T]) -> None:
        for it in others:
            for item in it:
                if item not in self._items:
                    self._items[item] = None

    def difference_update(self, *others: abc.Iterable[_T]) -> None:
        for it in others:
            for item in it:
                if item in self._items:
                    del self._items[item]


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
    def __init__(self, data: JsonType):
        self.id: int = int(data["id"])
        self.name: str = data["name"]

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

    @property
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
