from __future__ import annotations

import random
import string
import asyncio
import logging
from functools import wraps
from contextlib import suppress
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Union, List, MutableSet, Iterable, Iterator, Generic, TypeVar

from constants import JsonType


_V = TypeVar("_V")
_D = TypeVar("_D")
logger = logging.getLogger("TwitchDrops")
NONCE_CHARS = string.ascii_letters + string.digits


def timestamp(string: str) -> datetime:
    return datetime.strptime(string, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def create_nonce(length: int = 30) -> str:
    return ''.join(random.choices(NONCE_CHARS, k=length))


def deduplicate(iterable: Iterable[_V]) -> List[_V]:
    return list(OrderedDict.fromkeys(iterable).keys())


def task_wrapper(afunc):
    @wraps(afunc)
    async def wrapper(self, *args, **kwargs):
        try:
            await afunc(self, *args, **kwargs)
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


class OrderedSet(MutableSet[_V]):
    """
    Implementation of a set that preserves insertion order,
    based on OrderedDict with values set to None.
    """
    def __init__(self, iterable: Iterable[_V] = []):
        self._items: OrderedDict[_V, None] = OrderedDict((item, None) for item in iterable)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}([{', '.join(map(repr, self._items))}])"

    def __contains__(self, x: object) -> bool:
        return x in self._items

    def __iter__(self) -> Iterator[_V]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def add(self, item: _V) -> None:
        self._items[item] = None

    def discard(self, item: _V) -> None:
        with suppress(KeyError):
            del self._items[item]


class AwaitableValue(Generic[_V]):
    def __init__(self):
        self._value: _V
        self._event = asyncio.Event()

    def has_value(self) -> bool:
        return self._event.is_set()

    def get_with_default(self, default: _D) -> Union[_D, _V]:
        if self._event.is_set():
            return self._value
        return default

    async def get(self) -> _V:
        await self._event.wait()
        return self._value

    def set(self, value: _V) -> None:
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
