from __future__ import annotations

import sys
import ctypes
import signal
import asyncio
import logging
import argparse
import traceback
from typing import Optional

from twitch import Twitch
from version import __version__
from exceptions import CaptchaRequired
from constants import FORMATTER, LOG_PATH, WINDOW_TITLE


class ParsedArgs(argparse.Namespace):
    _verbose: int
    _debug_ws: bool
    _debug_gql: bool
    log: bool
    tray: bool
    no_run_check: bool
    game: Optional[str]

    @property
    def logging_level(self) -> int:
        return {
            0: logging.ERROR,
            1: logging.WARNING,
            2: logging.INFO,
            3: logging.DEBUG,
        }[min(self._verbose, 3)]

    @property
    def debug_ws(self) -> int:
        """
        If the debug flag is True, return DEBUG.
        If the main logging level is DEBUG, return INFO to avoid seeing raw messages.
        Otherwise, return NOTSET to inherit the global logging level.
        """
        if self._debug_ws:
            return logging.DEBUG
        elif self._verbose >= 3:
            return logging.INFO
        return logging.NOTSET

    @property
    def debug_gql(self) -> int:
        if self._debug_gql:
            return logging.DEBUG
        elif self._verbose >= 3:
            return logging.INFO
        return logging.NOTSET


# handle input parameters
# NOTE: due to using pythonw to run the main script, CLI help via '-h' and generally any
# console output is not available. The input arguments still work though.
parser = argparse.ArgumentParser(
    "Twitch Drops Miner (by DevilXD).exe",
    description="A program that allows you to mine timed drops on Twitch.",
)
parser.add_argument("--version", action="version", version=f"v{__version__}")
parser.add_argument("-v", dest="_verbose", action="count", default=0)
parser.add_argument("-g", "--game", default=None)
parser.add_argument("--tray", action="store_true")
parser.add_argument("--log", action="store_true")
# undocumented debug args
parser.add_argument("--no-run-check", dest="no_run_check", action="store_true")
parser.add_argument("--debug-ws", dest="_debug_ws", action="store_true")
parser.add_argument("--debug-gql", dest="_debug_gql", action="store_true")
options: ParsedArgs = parser.parse_args(namespace=ParsedArgs())
# check if we're not already running
try:
    exists = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
except AttributeError:
    # we're not on Windows - continue
    exists = False
if exists and not options.no_run_check:
    # already running - exit
    sys.exit()
# handle logging stuff
if options.logging_level > logging.DEBUG:
    # redirect the root logger into a NullHandler, effectively ignoring all logging calls
    # that aren't ours. This always runs, unless the main logging level is DEBUG or lower.
    logging.getLogger().addHandler(logging.NullHandler())
logger = logging.getLogger("TwitchDrops")
logger.setLevel(options.logging_level)
if options.log:
    handler = logging.FileHandler(LOG_PATH)
    handler.setFormatter(FORMATTER)
    logger.addHandler(handler)
logging.getLogger("TwitchDrops.gql").setLevel(options.debug_gql)
logging.getLogger("TwitchDrops.websocket").setLevel(options.debug_ws)

# client run
loop = asyncio.get_event_loop()
client = Twitch(options)
signal.signal(signal.SIGINT, lambda *_: client.close())
signal.signal(signal.SIGTERM, lambda *_: client.close())
try:
    loop.run_until_complete(client.run())
except CaptchaRequired:
    msg = "Your login attempt was denied by CAPTCHA.\nPlease try again in +12 hours."
    logger.exception(msg)
    client.prevent_close()
    client.print(msg)
except Exception:
    msg = "Fatal error encountered:\n"
    logger.exception(msg)
    client.prevent_close()
    client.print(msg)
    client.print(traceback.format_exc())
finally:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    loop.run_until_complete(client.shutdown())
if not client.gui.close_requested:
    client.print(
        "\nApplication Terminated.\nClose the window to exit the application."
    )
loop.run_until_complete(client.gui.wait_until_closed())
client.gui.stop()
client.gui.close_window()
loop.run_until_complete(loop.shutdown_asyncgens())
loop.close()
