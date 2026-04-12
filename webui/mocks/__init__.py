# Adapter classes that make WebUIManager look like the tkinter GUIManager.
#
# Background
# ----------
# twitch.py calls methods on a set of widget-like objects attached to the GUI
# manager (manager.status, manager.channels, manager.login, …).  Those objects
# were originally tkinter widgets.  The classes in this module are lightweight
# adapters that implement the same method signatures so that twitch.py requires
# no changes when the web UI is in use.
#
# How each class works
# --------------------
#
# The plain Python state lives on MainPanel (not WebUIManager) and persists so
# that late-joining clients can restore the full current view on page load
# without waiting for the next update.
#
# Correspondence to tkinter classes
# ----------------------------------
#   MockTray            → system tray icon         (no-op; no tray in browser)
#   MockStatus          → StatusBar                (header label + status card)
#   MockProgress        → CampaignProgress         (delegates to display_drop)
#   MockOutput          → ConsoleOutput            (forwards to manager.print)
#   MockChannels        → ChannelList              (manages _channel_map)
#   MockInventory       → InventoryOverview        (manages _inventory_campaigns)
#   MockLoginForm       → LoginForm                (device-code / password flow)
#   MockWebsocketStatus → WebsocketStatus          (manages _ws_data)
#   MockSettings        → settings panel widget    (no-op stubs)
#   MockTabs            → tab controller           (no-op stubs)

from __future__ import annotations

from .login_data import LoginData
from .tray import MockTray
from .status import MockStatus
from .progress import MockProgress
from .output import MockOutput
from .channels import MockChannels
from .inventory import MockInventory
from .login_form import MockLoginForm
from .websocket_status import MockWebsocketStatus
from .settings import MockSettings
from .tabs import MockTabs

__all__ = [
    "LoginData",
    "MockTray",
    "MockStatus",
    "MockProgress",
    "MockOutput",
    "MockChannels",
    "MockInventory",
    "MockLoginForm",
    "MockWebsocketStatus",
    "MockSettings",
    "MockTabs",
]
