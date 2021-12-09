from __future__ import annotations

__version__ = 3

import sys
import json
import ctypes
import logging
import asyncio
import warnings
import traceback
import threading
from typing import Any, Dict, NoReturn

from twitch import Twitch
from constants import SETTINGS_PATH

try:
    import win32api
    from win32con import CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
except (ImportError, ModuleNotFoundError):
    raise ImportError("You have to run 'python -m pip install pywin32' first")

# disable some warnings
warnings.simplefilter("ignore", RuntimeWarning)
warnings.simplefilter("ignore", DeprecationWarning)
# nice console title
try:
    ctypes.windll.kernel32.SetConsoleTitleW(f"Twitch Drops Miner v{__version__} (by DevilXD)")
except AttributeError:
    # ensure we're on windows and there was no import problems
    print("Only Windows supported!")
    quit()
assert sys.platform == "win32"


def terminate() -> NoReturn:
    forever = threading.Event()
    print("\nApplication Terminated.\nClose the console window to exit the application.")
    forever.wait()
    raise RuntimeError("Uh oh")  # this will never run, solely for MyPy


# handle extra stackable '-v' parameter, that switches the logging level
logging_level = logging.ERROR
if len(sys.argv) > 1:
    arg = sys.argv[1]
    if arg == ("-v", "-v1"):
        logging_level = logging.WARNING
    elif arg in ("-vv", "-v2"):
        logging_level = logging.INFO
    elif arg in ("-vvv", "-v3"):
        logging_level = logging.DEBUG
# handle logging stuff
logger = logging.getLogger("TwitchDrops")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("{levelname}: {message}", style='{'))
logger.addHandler(handler)
logger.setLevel(logging_level)
# handle settings
try:
    with open(SETTINGS_PATH, 'r', encoding="utf8") as file:
        settings: Dict[str, Any] = json.load(file)
except json.JSONDecodeError as exc:
    print(f"Error while reading the settings file:\n{str(exc)}")
    terminate()
except FileNotFoundError:
    settings = {}
# asyncio loop
loop = asyncio.get_event_loop()
# client init
client = Twitch(settings.get("username"), settings.get("password"))
# main task and it's close event
main_task = loop.create_task(client.run(settings.get("channels")))
close_event = threading.Event()


def clean_exit(code: int):
    if code not in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
        # filter only events we want
        return False
    # cancel the main task - this triggers the cleanup
    main_task.cancel()
    # wait until cleanup completes
    close_event.wait()
    # tell OS that we're free to exit now
    return True


# ensures clean exit upon closing the console
win32api.SetConsoleCtrlHandler(clean_exit, True)
try:
    loop.run_until_complete(main_task)
except (asyncio.CancelledError, KeyboardInterrupt):
    # KeyboardInterrupt causes run_until_complete to exit, but without cancelling the task.
    # The loop stops and thus the task gets frozen, until the loop runs again.
    # Because we don't want anything from there to actually run during cleanup,
    # we need to explicitly cancel the task ourselves here.
    main_task.cancel()
    # cancel all other tasks
    for task in asyncio.all_tasks(loop):
        if not task.done():
            task.cancel()
    # main_task was cancelled due to program shutting down - do the cleanup
    loop.run_until_complete(client.close())
    # notify we're free to exit
    close_event.set()
except Exception:
    # Remove the handler so it doesn't delay exit
    win32api.SetConsoleCtrlHandler(clean_exit, False)
    print("Fatal error encountered:\n")
    traceback.print_exc()
    terminate()
finally:
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()
