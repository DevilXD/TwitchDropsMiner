from __future__ import annotations

import random
import string
import asyncio
import logging
from functools import wraps
from contextlib import suppress
from datetime import datetime, timezone
from collections import abc, OrderedDict
from typing import Any, Literal, Generic, TypeVar, cast, TYPE_CHECKING

from constants import JsonType

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
logger = logging.getLogger("TwitchDrops")
NONCE_CHARS = string.ascii_letters + string.digits


def timestamp(string: str) -> datetime:
    return datetime.strptime(string, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


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


class OrderedSet(abc.MutableSet[_T]):
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
        return cast(abc.Coroutine[Any, Any, Literal[True]], self._event.wait())

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
        return hash((self.__class__.__name__, self.id))
