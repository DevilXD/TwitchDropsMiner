from __future__ import annotations

# import an additional thing for proper PyInstaller freeze support
from multiprocessing import freeze_support


if __name__ == "__main__":
    freeze_support()
    import io
    import sys
    import signal
    import asyncio
    import logging
    import argparse
    import warnings
    import traceback
    import threading
    import tkinter as tk
    from tkinter import messagebox
    from typing import IO, NoReturn, Optional, TYPE_CHECKING

    try:
        from web.app import run_web_server, initialize  # Add 'initialize' to the import
        HAS_WEB_INTERFACE = True
    except ImportError:
        HAS_WEB_INTERFACE = False
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        # truststore is not required, just recommended
        pass

    from translate import _
    from twitch import Twitch
    from settings import Settings
    from version import __version__
    from exceptions import CaptchaRequired
    from utils import lock_file, resource_path, set_root_icon
    from constants import LOGGING_LEVELS, SELF_PATH, FILE_FORMATTER, LOG_PATH, LOCK_PATH

    if TYPE_CHECKING:
        from _typeshed import SupportsWrite
    warnings.simplefilter("default", ResourceWarning)

    # import tracemalloc
    # tracemalloc.start(3)

    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or higher is required")

    class Parser(argparse.ArgumentParser):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._message: io.StringIO = io.StringIO()

        def _print_message(self, message: str, file: SupportsWrite[str] | None = None) -> None:
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
        dump: bool
        # Web interface options
        enable_web: bool = False
        web_host: str = "127.0.0.1"
        web_port: int = 8080

        @property
        def log_level(self) -> int:
            return min(self._verbose, 4)

        @property
        def debug_ws(self) -> int:
            """
            If the debug flag is True, return DEBUG.
            If the main logging level is DEBUG, return INFO to avoid seeing raw messages.
            Otherwise, return NOTSET to inherit the global logging level.
            """
            if self._debug_ws:
                return logging.DEBUG
            elif self._verbose >= 4:
                return logging.INFO
            return logging.NOTSET

        @property
        def debug_gql(self) -> int:
            if self._debug_gql:
                return logging.DEBUG
            elif self._verbose >= 4:
                return logging.INFO
            return logging.NOTSET

    # Initialize variables
    exit_status = 0
    log_stringio = io.StringIO()

    # handle input parameters
    # NOTE: parser output is shown via message box
    # we also need a dummy invisible window for the parser
    root = tk.Tk()
    root.overrideredirect(True)
    root.withdraw()
    set_root_icon(root, resource_path("icons/pickaxe.ico"))
    root.update()
    parser = Parser(
        SELF_PATH.name,
        description="A program that allows you to mine timed drops on Twitch.",
    )
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    parser.add_argument("-v", dest="_verbose", action="count", default=0)
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--dump", action="store_true")
    
    # Web interface options
    if HAS_WEB_INTERFACE:
        parser.add_argument(
            "--web",
            dest="enable_web",
            action="store_true",
            help="Enable the web interface"
        )
        parser.add_argument(
            "--web-host",
            dest="web_host",
            type=str,
            default="127.0.0.1",
            help="Web interface host address (default: 127.0.0.1)"
        )
        parser.add_argument(
            "--web-port",
            dest="web_port",
            type=int,
            default=8080,
            help="Web interface port (default: 8080)"
        )
    
    # undocumented debug args
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
    # client run
    async def main() -> None:
        global exit_status
        # setup logging
        log_level = LOGGING_LEVELS[args.log_level]
        LOG_PATH.parent.mkdir(exist_ok=True)
        # Use FILE_FORMATTER._fmt and FILE_FORMATTER.datefmt for correct logging.basicConfig usage
        logging.basicConfig(
            level=log_level,
            format=FILE_FORMATTER._fmt,
            datefmt=FILE_FORMATTER.datefmt,
            style='{',
            force=True,
            filename=LOG_PATH,
            encoding="utf-8",
            filemode="w",
        )

        loop = asyncio.get_running_loop()
        log = logging.getLogger("main")
        log.info(f"Starting TwitchDropsMiner {__version__}")

        # suppress urllib3 debug warnings
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        # suppress PIL debug info spam
        logging.getLogger("PIL").setLevel(logging.INFO)
        # suppress py warning coming from browser.py (from obviated dependency of aiohttp)
        warnings.filterwarnings("ignore", "unclosed", ResourceWarning)
        warnings.filterwarnings("ignore", "Unclosed.*<ssl.SSLSocket.*>", ResourceWarning)
        
        # Update settings with web interface status before creating Twitch instance
        if HAS_WEB_INTERFACE and args.enable_web:
            settings.gui_enabled = False
        else:
            settings.gui_enabled = True
            
        client = Twitch(settings)
        
        # Start web server if enabled and available
        if HAS_WEB_INTERFACE and args.enable_web:
            log.info(f"Starting web interface on {args.web_host}:{args.web_port}")
            client.print(f"Starting web interface on http://{args.web_host}:{args.web_port}")
            
            # Initialize the web app with the event loop and client instance
            initialize(loop, client)
            
            # Start the web server in a separate thread
            web_thread = threading.Thread(
                target=run_web_server,
                args=(args.web_host, args.web_port, False, client),
                daemon=True
            )
            web_thread.start()
            
        if sys.platform == "linux":
            loop.add_signal_handler(signal.SIGINT, lambda *_: client.gui.close())
            loop.add_signal_handler(signal.SIGTERM, lambda *_: client.gui.close())
        try:
            await client.run()
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
            if sys.platform == "linux":
                loop.remove_signal_handler(signal.SIGINT)
                loop.remove_signal_handler(signal.SIGTERM)
            client.print(_("gui", "status", "exiting"))
            await client.shutdown()
        if client.settings.gui_enabled:
            if not client.gui.close_requested:
                # user didn't request the closure
                client.gui.tray.change_icon("error")
                client.print(_("status", "terminated"))
                client.gui.status.update(_("gui", "status", "terminated"))
                # notify the user about the closure
                client.gui.grab_attention(sound=True)
            await client.gui.wait_until_closed()
        # save the application state
        # NOTE: we have to do it after wait_until_closed,
        # because the user can alter some settings between app termination and closing the window
        client.save(force=True)
        if client.settings.gui_enabled:
            client.gui.stop()
            client.gui.close_window()
        sys.exit(exit_status)

    try:
        # use lock_file to check if we're not already running
        success, file = lock_file(LOCK_PATH)
        if not success:
            # already running - exit
            sys.exit(3)

        asyncio.run(main())
    finally:
        try:
            file.close()
        except:
            pass
