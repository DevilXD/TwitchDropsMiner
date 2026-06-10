from __future__ import annotations

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

    parser = argparse.ArgumentParser(
        SELF_PATH.name,
        description="Twitch Drops Miner - web server mode (port 5001)",
    )
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    parser.add_argument("-v", dest="_verbose", action="count", default=0)
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--tray", action="store_true", help=argparse.SUPPRESS)  # kept for compat
    parser.add_argument("--debug-ws", dest="_debug_ws", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--debug-gql", dest="_debug_gql", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(namespace=ParsedArgs())

    try:
        settings = Settings(args)
    except Exception:
        print(f"Settings error:\n{traceback.format_exc()}", file=sys.stderr)
        sys.exit(4)

    async def main():
        try:
            _.set_language(settings.language)
        except ValueError:
            pass

        if settings.logging_level > logging.DEBUG:
            logging.getLogger().addHandler(logging.NullHandler())
        logger = logging.getLogger("TwitchDrops")
        logger.setLevel(settings.logging_level)
        if settings.log:
            handler = logging.FileHandler(LOG_PATH)
            handler.setFormatter(FILE_FORMATTER)
            logger.addHandler(handler)
        logging.getLogger("TwitchDrops.gql").setLevel(settings.debug_gql)
        logging.getLogger("TwitchDrops.websocket").setLevel(settings.debug_ws)

        exit_status = 0
        client = Twitch(settings)
        loop = asyncio.get_running_loop()
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
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)
            client.print(_("gui", "status", "exiting"))
            await client.shutdown()
        if not client.gui.close_requested:
            client.gui.tray.change_icon("error")
            client.print(_("status", "terminated"))
            client.gui.status.update(_("gui", "status", "terminated"))
        await client.gui.wait_until_closed()
        client.save(force=True)
        client.gui.stop()
        client.gui.close_window()
        sys.exit(exit_status)

    try:
        success, file = lock_file(LOCK_PATH)
        if not success:
            print("Another instance is already running.", file=sys.stderr)
            sys.exit(3)

        print(f"Starting Twitch Drops Miner web server on http://0.0.0.0:5001")
        asyncio.run(main())
    finally:
        file.close()
