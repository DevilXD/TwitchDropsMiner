from __future__ import annotations

# import an additional thing for proper PyInstaller freeze support
from multiprocessing import freeze_support
from datetime import datetime


if __name__ == "__main__":
    print(f"{datetime.now().strftime('%Y-%m-%d %X')}: Starting: Twitch Drops Miner")
    freeze_support()
    import io
    import sys
    import signal
    import asyncio
    import logging
    import argparse
    import warnings
    import traceback
    import tkinter as tk
    from tkinter import messagebox
    from typing import IO, NoReturn

    from PIL.ImageTk import PhotoImage
    from PIL import Image as Image_module

    if sys.platform == "win32":
        import win32gui

    from translate import _
    from twitch import Twitch
    from settings import Settings
    from utils import resource_path
    from version import __version__
    from exceptions import CaptchaRequired
    from constants import CALL, SELF_PATH, FILE_FORMATTER, LOG_PATH, WINDOW_TITLE

    warnings.simplefilter("default", ResourceWarning)

    class Parser(argparse.ArgumentParser):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._message: io.StringIO = io.StringIO()

        def _print_message(self, message: str, file: IO[str] | None = None) -> None:
            self._message.write(message)
            # print(message, file=self._message)

        def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
            try:
                super().exit(status, message)  # sys.exit(2)
            finally:
                messagebox.showerror("Argument Parser Error", self._message.getvalue())

    class ParsedArgs(argparse.Namespace):
        _verbose: int
        _debug_ws: bool
        _debug_gql: bool
        log: bool
        tray: bool
        no_run_check: bool

        # TODO: replace int with union of literal values once typeshed updates
        @property
        def logging_level(self) -> int:
            return {
                0: logging.ERROR,
                1: logging.WARNING,
                2: logging.INFO,
                3: CALL,
                4: logging.DEBUG,
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
    # NOTE: parser output is shown via message box
    # we also need a dummy invisible window for the parser
    root = tk.Tk()
    root.overrideredirect(True)
    root.withdraw()
    root.iconphoto(
        True, PhotoImage(master=root, image=Image_module.open(resource_path("pickaxe.ico")))
    )
    root.update()
    parser = Parser(
        SELF_PATH.name,
        description="A program that allows you to mine timed drops on Twitch.",
    )
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    parser.add_argument("-v", dest="_verbose", action="count", default=0)
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--log", action="store_true")
    # undocumented debug args
    parser.add_argument(
        "--no-run-check", dest="no_run_check", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--debug-ws", dest="_debug_ws", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--debug-gql", dest="_debug_gql", action="store_true", help=argparse.SUPPRESS
    )
    args = parser.parse_args(namespace=ParsedArgs())
    # load settings
    try:
        settings = Settings(args)
    except Exception:
        messagebox.showerror(
            "Settings error",
            f"There was an error while loading the settings file:\n\n{traceback.format_exc()}"
        )
        sys.exit(4)
    # dummy window isn't needed anymore
    root.destroy()
    # get rid of unneeded objects
    del root, parser

    # check if we're not already running
    if sys.platform == "win32":
        try:
            exists = win32gui.FindWindow(None, WINDOW_TITLE)
        except AttributeError:
            # we're not on Windows - continue
            exists = False
        if exists and not settings.no_run_check:
            # already running - exit
            sys.exit(3)

    # set language
    try:
        _.set_language(settings.language)
    except ValueError:
        # this language doesn't exist - stick to English
        pass

    # handle logging stuff
    if settings.logging_level > logging.DEBUG:
        # redirect the root logger into a NullHandler, effectively ignoring all logging calls
        # that aren't ours. This always runs, unless the main logging level is DEBUG or lower.
        logging.getLogger().addHandler(logging.NullHandler())
    logger = logging.getLogger("TwitchDrops")
    logger.setLevel(settings.logging_level)
    if settings.log:
        handler = logging.FileHandler(LOG_PATH)
        handler.setFormatter(FILE_FORMATTER)
        logger.addHandler(handler)
    logging.getLogger("TwitchDrops.gql").setLevel(settings.debug_gql)
    logging.getLogger("TwitchDrops.websocket").setLevel(settings.debug_ws)

    # client run
    exit_status = 0
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = Twitch(settings)
    signal.signal(signal.SIGINT, lambda *_: client.gui.close())
    signal.signal(signal.SIGTERM, lambda *_: client.gui.close())
    try:
        loop.run_until_complete(client.run())
    except CaptchaRequired:
        exit_status = 1
        client.prevent_close()
        client.print(_("error", "captcha"))
    except Exception:
        exit_status = 1
        client.prevent_close()
        client.print("Fatal error encountered:\n")
        client.print(traceback.format_exc())
    finally:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        client.print(_("gui", "status", "exiting"))
        loop.run_until_complete(client.shutdown())
    if not client.gui.close_requested:
        client.print(_("status", "terminated"))
        client.gui.status.update(_("gui", "status", "terminated"))
    loop.run_until_complete(client.gui.wait_until_closed())
    # save the application state
    # NOTE: we have to do it after wait_until_closed,
    # because the user can alter some settings between app termination and closing the window
    client.save(force=True)
    client.gui.stop()
    client.gui.close_window()
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()
    sys.exit(exit_status)
