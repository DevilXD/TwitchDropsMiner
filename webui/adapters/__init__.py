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
#   TrayIconAdapter         → TrayIcon           (no-op; no tray in browser)
#   StatusBarAdapter        → StatusBar          (header label + status card)
#   CampaignProgressAdapter → CampaignProgress   (delegates to display_drop)
#   ConsoleOutputAdapter    → ConsoleOutput      (forwards to manager.print)
#   ChannelListAdapter      → ChannelList        (manages _channel_map)
#   InventoryAdapter        → InventoryOverview  (manages _inventory_campaigns)
#   LoginFormAdapter        → LoginForm          (device-code / password flow)
#   WebsocketStatusAdapter  → WebsocketStatus    (manages _ws_data)
#   SettingsAdapter         → SettingsPanel      (no-op stubs)
#   TabsAdapter             → Notebook (Tabs)    (no-op stubs)

from __future__ import annotations

from .tray_icon import TrayIconAdapter
from .status_bar import StatusBarAdapter
from .campaign_progress import CampaignProgressAdapter
from .console_output import ConsoleOutputAdapter
from .channel_list import ChannelListAdapter
from .inventory_overview import InventoryOverviewAdapter
from .login_form import LoginData, LoginFormAdapter
from .websocket_status import WebsocketStatusAdapter
from .settings import SettingsAdapter
from .tabs import TabsAdapter

__all__ = [
    "LoginData",
    "TrayIconAdapter",
    "StatusBarAdapter",
    "CampaignProgressAdapter",
    "ConsoleOutputAdapter",
    "ChannelListAdapter",
    "InventoryOverviewAdapter",
    "LoginFormAdapter",
    "WebsocketStatusAdapter",
    "SettingsAdapter",
    "TabsAdapter",
]
