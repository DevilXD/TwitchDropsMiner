from __future__ import annotations

import ssl
from typing import Any

import certifi

_orig_create_default_context = ssl.create_default_context


def _create_default_context(*args: Any, **kwargs: Any) -> ssl.SSLContext:
    if (
        kwargs.get("cafile") is None
        and kwargs.get("capath") is None
        and kwargs.get("cadata") is None
    ):
        kwargs = {**kwargs, "cafile": certifi.where()}
    return _orig_create_default_context(*args, **kwargs)


ssl.create_default_context = _create_default_context

import aiohttp


def create_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def create_tcp_connector(**kwargs: Any) -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(ssl=create_ssl_context(), **kwargs)


def create_session(**kwargs: Any) -> aiohttp.ClientSession:
    if "connector" not in kwargs:
        kwargs = {**kwargs, "connector": create_tcp_connector()}
    return aiohttp.ClientSession(**kwargs)
