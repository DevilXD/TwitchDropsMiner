from __future__ import annotations

import logging
import argparse
from typing import Optional

from twitch import Twitch
from version import __version__


class ParsedArgs(argparse.Namespace):
    _verbose: int
    _debug_ws: bool
    _debug_gql: bool
    game: Optional[str]

    @property
    def logging_level(self) -> int:
        return {
            0: logging.ERROR,
            1: logging.WARNING,
            2: logging.INFO,
            3: logging.DEBUG,
        }.get(self._verbose, logging.DEBUG)

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
parser = argparse.ArgumentParser(
    f"TwitchDropsMiner.v{__version__}.exe",
    description="A program that allows you to mine timed drops on Twitch.",
)
parser.add_argument("-V", "--version", action="version", version=f"v{__version__}")
parser.add_argument("-v", dest="_verbose", action="count", default=0)
parser.add_argument("--debug-ws", dest="_debug_ws", action="store_true")
parser.add_argument("--debug-gql", dest="_debug_gql", action="store_true")
parser.add_argument("-g", "--game", default=None)
options: ParsedArgs = parser.parse_args(namespace=ParsedArgs())
# handle logging stuff
if options.logging_level > logging.DEBUG:
    # redirect the root logger into a NullHandler, effectively ignoring all logging calls
    # that aren't ours. This always runs, unless the main logging level is DEBUG or below.
    logging.getLogger().addHandler(logging.NullHandler())
logger = logging.getLogger("TwitchDrops")
logger.setLevel(options.logging_level)
logging.getLogger("TwitchDrops.gql").setLevel(options.debug_gql)
logging.getLogger("TwitchDrops.websocket").setLevel(options.debug_ws)
# client run
client = Twitch(options)
client.start()
