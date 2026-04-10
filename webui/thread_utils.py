"""Thread-dispatch helpers for crossing the main-loop ↔ NiceGUI-loop boundary.

Both twitch.py (main asyncio loop) and NiceGUI (its own asyncio event loop) need to
call into each other. Use the helpers below to make that automatic — no manual
call_soon_threadsafe or nested closures at the call site.

All helpers accept a WebUIManager or Mock* instance as the first argument and
resolve the target loop from it:
  - NiceGUI loop: self._nicegui_loop  (WebUIManager)  or  self._manager._nicegui_loop  (Mock*)
  - main loop:    self._main_loop     (WebUIManager)  or  self._manager._main_loop     (Mock*)

call_on_nicegui(obj, fn) — schedule fn() on the NiceGUI event loop (inline use)
call_on_main_loop(obj, fn) — schedule fn() on the main asyncio loop (inline use)
@on_nicegui_loop — decorator form of call_on_nicegui for whole methods
@on_main_loop    — decorator form of call_on_main_loop for whole methods
"""

from __future__ import annotations

import asyncio
import functools


def _dispatch(loop: asyncio.AbstractEventLoop | None, fn):
    """Core dispatch: run fn() on loop, scheduling cross-thread if needed."""
    if loop is None:
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        return fn()
    loop.call_soon_threadsafe(fn)


def call_on_nicegui(obj, fn):
    """Schedule fn() on the NiceGUI event loop. obj is a WebUIManager or Mock* instance."""
    _dispatch(
        getattr(obj, '_nicegui_loop', None) or obj._manager._nicegui_loop,
        fn,
    )


def call_on_main_loop(obj, fn):
    """Schedule fn() on the main asyncio event loop. obj is a WebUIManager or Mock* instance."""
    _dispatch(
        getattr(obj, '_main_loop', None) or obj._manager._main_loop,
        fn,
    )


def on_nicegui_loop(method):
    """Decorator form of call_on_nicegui — ensures the whole method runs on the NiceGUI loop.

    - Already on the NiceGUI loop → calls directly (re-entrant safe).
    - On any other thread/loop → schedules via call_soon_threadsafe.
    - NiceGUI loop not yet started → silently drops (returns None).
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        return call_on_nicegui(self, functools.partial(method, self, *args, **kwargs))
    return wrapper


def on_main_loop(method):
    """Decorator form of call_on_main_loop — ensures the whole method runs on the main loop."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        return call_on_main_loop(self, functools.partial(method, self, *args, **kwargs))
    return wrapper
