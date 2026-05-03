"""
WebUI entry point for Twitch Drops Miner.

This entry point starts the NiceGUI web interface first and runs the Twitch
backend within the same asyncio event loop, eliminating the need for thread
synchronization between the UI and backend.
"""

from __future__ import annotations

# import an additional thing for proper PyInstaller freeze support
from multiprocessing import freeze_support

if __name__ == "__main__":
    freeze_support()
    import sys
    import signal
    import asyncio
    import logging
    import argparse
    import warnings
    import traceback

    import truststore

    truststore.inject_into_ssl()

    from translate import _

    # Install a stub gui module so twitch.py's `from gui import GUIManager`
    # resolves to WebUIManager without loading tkinter.
    import types as _types
    from webui import WebUIManager as _WebUIManager

    _gui_stub = _types.ModuleType("gui")
    _gui_stub.GUIManager = _WebUIManager  # type: ignore[attr-defined]
    sys.modules["gui"] = _gui_stub
    del _types, _WebUIManager, _gui_stub

    from twitch import Twitch
    from settings import Settings
    from version import __version__
    from exceptions import CaptchaRequired
    from utils import lock_file
    from constants import LOGGING_LEVELS, SELF_PATH, FILE_FORMATTER, LOG_PATH, LOCK_PATH

    warnings.simplefilter("default", ResourceWarning)

    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or higher is required")

    class ParsedArgs(argparse.Namespace):
        _verbose: int
        _debug_ws: bool
        _debug_gql: bool
        log: bool
        stdlog: bool
        tray: bool
        dump: bool

        @property
        def logging_level(self) -> int:
            return LOGGING_LEVELS[min(self._verbose, 4)]

        @property
        def debug_ws(self) -> int:
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

    # handle input parameters
    parser = argparse.ArgumentParser(
        SELF_PATH.name,
        description="A program that allows you to mine timed drops on Twitch.",
    )
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    parser.add_argument("-v", dest="_verbose", action="count", default=0)
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--stdlog", action="store_true")
    parser.add_argument("--dump", action="store_true")
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
        print("ERROR: Settings error")
        print("There was an error while loading the settings file.")
        print("This is a docker permissions issue or you mounted the wrong folder.")
        print(
            "Check the readme at https://github.com/fireph/docker-twitch-drops-miner."
        )
        print("DO NOT report this issue to the DevilXD/TwitchDropsMiner repository!")
        print()
        traceback.print_exc()
        sys.exit(4)

    del parser

    # WebUI setup - we'll use NiceGUI's event loop for everything
    try:
        from nicegui import ui, app
    except ImportError:
        print("ERROR: NiceGUI is not installed.")
        print("Install it with: pip install nicegui")
        sys.exit(1)
    from pathlib import Path

    # Global state for the Twitch client
    twitch_client: Twitch | None = None
    exit_status = 0

    async def run_twitch_backend():
        """Run the Twitch backend within NiceGUI's event loop."""
        global twitch_client, exit_status

        # set language
        try:
            _.set_language(settings.language)
        except ValueError:
            pass

        # handle logging stuff
        if settings.logging_level > logging.DEBUG:
            logging.getLogger().addHandler(logging.NullHandler())
        logger = logging.getLogger("TwitchDrops")
        logger.setLevel(settings.logging_level)
        if settings.log:
            handler = logging.FileHandler(LOG_PATH)
            handler.setFormatter(FILE_FORMATTER)
            logger.addHandler(handler)
        if settings.stdlog:
            handler_stdout = logging.StreamHandler(sys.stdout)
            handler_stdout.setFormatter(FILE_FORMATTER)
            handler_stdout.addFilter(lambda record: record.levelno <= logging.WARNING)
            logger.addHandler(handler_stdout)
            handler_stderr = logging.StreamHandler(sys.stderr)
            handler_stderr.setFormatter(FILE_FORMATTER)
            handler_stderr.addFilter(lambda record: record.levelno >= logging.ERROR)
            logger.addHandler(handler_stderr)
        logging.getLogger("TwitchDrops.gql").setLevel(settings.debug_gql)
        logging.getLogger("TwitchDrops.websocket").setLevel(settings.debug_ws)

        # Create Twitch client - this will create WebUIManager which registers
        # NiceGUI page handlers. Must run on the event loop thread because
        # route registration is not thread-safe.
        client = Twitch(settings)
        twitch_client = client

        loop = asyncio.get_running_loop()
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

        if not client.gui.close_requested:
            client.gui.tray.change_icon("error")
            client.print(_("status", "terminated"))
            client.gui.status.update(_("gui", "status", "terminated"))
            client.gui.grab_attention(sound=True)

        await client.gui.wait_until_closed()
        client.save(force=True)
        client.gui.stop()
        client.gui.close_window()

    @app.on_startup
    async def on_startup():
        """Called when NiceGUI server starts - begin Twitch backend initialization."""
        # Start the backend in a separate task so it doesn't block server startup
        asyncio.create_task(start_backend())

    async def start_backend():
        """Initialize Twitch client and run the backend."""
        global twitch_client, exit_status
        try:
            await run_twitch_backend()
        except Exception as e:
            print(f"Backend error: {e}")
            traceback.print_exc()
            app.shutdown()

    @app.on_shutdown
    async def on_shutdown():
        """Called when NiceGUI server shuts down."""
        global twitch_client
        if twitch_client is not None:
            twitch_client.gui.close()

    # Start NiceGUI - this blocks until shutdown
    try:
        success, file = lock_file(LOCK_PATH)
        if not success:
            sys.exit(3)

        # Get host/port from settings object (uses __getattr__)
        host = getattr(settings, "webui_host", "0.0.0.0")
        port = getattr(settings, "webui_port", 8080)

        try:
            ui.run(
                host=host,
                port=port,
                title="Twitch Drops Miner",
                show=False,
                reload=False,
                favicon=Path(__file__).parent / "icons" / "pickaxe.ico",
            )
        except KeyboardInterrupt:
            pass
        finally:
            file.close()
            sys.exit(exit_status)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
