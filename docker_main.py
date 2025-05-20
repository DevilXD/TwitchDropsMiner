#!/usr/bin/env python3
from __future__ import annotations

"""
Docker-optimized entry point for TwitchDropsMiner
This file is designed to run the application in web mode without GUI dependencies
"""

# Standard library imports
import io
import os
import sys
import signal
import asyncio
import logging
import argparse
import warnings
import traceback
import threading
from pathlib import Path

# Apply headless GUI patches first - this is critical
from headless_gui import apply_headless_patches
apply_headless_patches()

# Now we can safely import our application modules
from web.app import run_web_server, initialize
from translate import _
from twitch import Twitch
from settings import Settings, default_settings
from version import __version__
from exceptions import CaptchaRequired
from utils import lock_file, json_load, json_save
from constants import LOG_PATH, LOCK_PATH

# Try to improve SSL support
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    # truststore is not required, just recommended
    pass


# Configure logging
LOG_PATH.parent.mkdir(exist_ok=True, parents=True)
logging.basicConfig(
    level=logging.INFO,
    format='{asctime} [{levelname}] {name}: {message}',
    datefmt='%Y-%m-%d %H:%M:%S',
    style='{',
    filename=LOG_PATH,
    encoding="utf-8",
    filemode="w",
)

# Suppress warnings
warnings.simplefilter("default", ResourceWarning)
warnings.filterwarnings("ignore", "unclosed", ResourceWarning)
warnings.filterwarnings("ignore", "Unclosed.*<ssl.SSLSocket.*>", ResourceWarning)

# Define ParsedArgs class to ensure compatibility with Settings class
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
        return min(getattr(self, '_verbose', 0), 4)

    @property
    def debug_ws(self) -> int:
        if getattr(self, '_debug_ws', False):
            return logging.DEBUG
        elif getattr(self, '_verbose', 0) >= 4:
            return logging.INFO
        return logging.NOTSET

    @property
    def debug_gql(self) -> int:
        if getattr(self, '_debug_gql', False):
            return logging.DEBUG
        elif getattr(self, '_verbose', 0) >= 4:
            return logging.INFO
        return logging.NOTSET

async def main():
    # Create logger for the main process
    log = logging.getLogger("docker-main")
    log.info(f"Starting TwitchDropsMiner {__version__} in Docker/Web Mode")
    print(f"Starting TwitchDropsMiner {__version__} in Docker/Web Mode")

    # Web interface configuration (for Docker)
    WEB_HOST = "0.0.0.0"  # Listen on all interfaces
    WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))    # Create args for settings using ParsedArgs from main.py
    args = ParsedArgs()
    # Set Docker-specific defaults
    args._verbose = 0
    args._debug_ws = False
    args._debug_gql = False
    args.log = True
    args.tray = False
    args.dump = False
    # Web interface options
    args.enable_web = True
    args.web_host = "0.0.0.0"  # Listen on all interfaces
    args.web_port = WEB_PORT
    
    # Load settings
    try:
        # Create settings with our ParsedArgs instance
        settings = Settings(args)
        
        # Force headless/web mode for Docker environment
        settings.gui_enabled = False
    except Exception as e:
        log.error(f"Settings error: {traceback.format_exc()}")
        print(f"Settings error: {e}")
        return 4
    
    # Initialize the client
    client = Twitch(settings)
    # Get the event loop
    loop = asyncio.get_running_loop()
    
    # Initialize and start the web server
    log.info(f"Starting web interface on {WEB_HOST}:{WEB_PORT}")
    print(f"Starting web interface on http://{WEB_HOST}:{WEB_PORT}")
    
    # Initialize the web app with the event loop and client instance
    initialize(loop, client)
    
    # Start the web server in a separate thread
    web_thread = threading.Thread(
        target=run_web_server,
        args=(WEB_HOST, WEB_PORT, False, client),
        daemon=True
    )
    web_thread.start()
    
    # Set up signal handlers for clean shutdown
    if sys.platform == "linux":
        # Use lambda functions just like in main.py
        loop.add_signal_handler(signal.SIGINT, lambda *_: asyncio.create_task(client.shutdown()))
        loop.add_signal_handler(signal.SIGTERM, lambda *_: asyncio.create_task(client.shutdown()))
    
    # Run the client
    exit_status = 0
    try:
        await client.run()
    except CaptchaRequired:
        exit_status = 1
        client.print(_("error", "captcha"))
    except Exception:
        exit_status = 1
        client.print("Fatal error encountered:\n")
        client.print(traceback.format_exc())
    finally:
        if sys.platform == "linux":
            try:
                loop.remove_signal_handler(signal.SIGINT)
                loop.remove_signal_handler(signal.SIGTERM)
            except:
                pass
        client.print(_("gui", "status", "exiting"))
        await client.shutdown()
    
    # Save application state
    client.save(force=True)
    return exit_status

if __name__ == "__main__":
    # Check if already running
    success, lock_file_handle = lock_file(LOCK_PATH)
    if not success:
        print("TwitchDropsMiner is already running. Exiting.")
        sys.exit(3)
    
    try:
        # Run the main async function
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    finally:
        try:
            if 'lock_file_handle' in locals() and lock_file_handle:
                lock_file_handle.close()
        except Exception as e:
            print(f"Error closing lock file: {e}")
