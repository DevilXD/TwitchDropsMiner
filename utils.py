from __future__ import annotations

import sys
import json
import random
import string
import asyncio
import logging
import traceback
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

from constants import WORKING_DIR, JsonType

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


def format_traceback(exc: BaseException, **kwargs: Any) -> str:
    """
    Like `traceback.print_exc` but returns a string. Uses the passed-in exception.
    Any additional `**kwargs` are passed to the underlaying `traceback.format_exception`.
    """
    return ''.join(traceback.format_exception(type(exc), exc, **kwargs))


def json_minify(data: JsonType | list[JsonType]) -> str:
    """
    Returns minified JSON for payload usage.
    """
    return json.dumps(data, separators=(',', ':'))


def resource_path(relative_path: Path | str) -> Path:
    """
    Get an absolute path to a bundled resource.

    Works for dev and for PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller's folder where the one-file app is unpacked
        meipass: str = getattr(sys, "_MEIPASS")
        base_path = Path(meipass)
    else:
        base_path = WORKING_DIR
    return base_path.joinpath(relative_path)


def timestamp(string: str) -> datetime:
    return datetime.strptime(string, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


NONCE_CHARS = string.ascii_letters + string.digits


def create_nonce(length: int = 30) -> str:
    return ''.join(random.choices(NONCE_CHARS, k=length))


def deduplicate(iterable: abc.Iterable[_T]) -> list[_T]:
    return list(OrderedDict.fromkeys(iterable).keys())


def task_wrapper(
    afunc: abc.Callable[_P, abc.Coroutine[Any, Any, _T]]
) -> abc.Callable[_P, abc.Coroutine[Any, Any, _T]]:
    @wraps(afunc)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs):
        try:
            await afunc(*args, **kwargs)
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
    return obj


def _deserialize(obj: JsonType) -> Any:
    if "__type" in obj:
        obj_type = obj["__type"]
        if obj_type in SERIALIZE_ENV:
            return SERIALIZE_ENV[obj_type](obj["data"])
        else:
            return _MISSING
    return obj


def json_load(path: Path, defaults: _JSON_T) -> _JSON_T:
    combined: JsonType = dict(defaults)
    if path.exists():
        with open(path, 'r') as file:
            combined.update(_remove_missing(json.load(file, object_hook=_deserialize)))
    return cast(_JSON_T, combined)


def json_save(path: Path, contents: Mapping[Any, Any]) -> None:
    with open(path, 'w') as file:
        json.dump(contents, file, default=_serialize, sort_keys=True, indent=4)


class ExponentialBackoff:
    def __init__(
        self,
        *,
        base: float = 2,
        variance: float | tuple[float, float] = 0.1,
        shift: float = -1,
        maximum: float = 300,
    ):
        if base <= 1:
            raise ValueError("base has to be greater than 1")
        self.exp: int = 0
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

    def __iter__(self) -> abc.Iterator[float]:
        return self

    def __next__(self) -> float:
        value: float = (
            pow(self.base, self.exp)
            * random.uniform(self.variance_min, self.variance_max)
            + self.shift
        )
        if value > self.maximum:
            return self.maximum
        # NOTE: variance can cause the returned value to be lower than the previous one already,
        # so this should be safe to move past the first return,
        # to prevent the exponent from getting very big after reaching max and many iterations
        self.exp += 1
        return value

    def reset(self) -> None:
        self.exp = 0


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
        return cast("abc.Coroutine[Any, Any, Literal[True]]", self._event.wait())

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

    def __eq__(self, other: object):
        if isinstance(other, self.__class__):
            return self.id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        return self.id
