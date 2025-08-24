from __future__ import annotations

import sys
from typing import Callable, Optional


# Headless GUI implementation for web mode
class DummyProgress:
    """A dummy progress class for web mode."""
    
    def minute_almost_done(self) -> bool:
        # In headless mode, always return False to continue normal processing
        return False
    
    def stop_timer(self):
        pass
    
    def display(self, drop=None, *, countdown: bool = True, subone: bool = False):
        pass


class DummyChannels:
    """A dummy channels class for web mode."""
    
    def clear(self):
        pass
    
    def set_watching(self, channel):
        pass
    
    def clear_watching(self):
        pass
    
    def get_selection(self):
        return None


class DummyGUI:
    """A simple placeholder for GUI functionality when running in web mode."""
    
    def __init__(self, client=None):
        self.client = client
        self.close_requested = False
        self.status = DummyStatus()
        self.tray = DummyTray()
        self.progress = DummyProgress()
        self.channels = DummyChannels()
    
    def close(self):
        self.close_requested = True
    
    def grab_attention(self, sound=False):
        pass
    
    async def wait_until_closed(self):
        return
    
    def stop(self):
        pass
    
    def close_window(self):
        pass
    
    def set_games(self, games):
        pass
    
    def clear_drop(self):
        pass


class DummyStatus:
    """A dummy status class for web mode."""
    
    def update(self, message):
        print(f"Status update: {message}")


class DummyTray:
    """A dummy tray class for web mode."""
    
    def change_icon(self, icon_name):
        pass


# For monkey patching the regular GUI import
class GUIManager(DummyGUI):
    """A placeholder for the GUI manager in web mode."""
    
    def __init__(self, client):
        super().__init__(client)


# Dummy classes for other GUI components that might be imported
class LoginForm:
    pass

class WebsocketStatus:
    pass

class InventoryOverview:
    pass

class ChannelList:
    pass


def apply_headless_patches():
    """Apply patches to make the application work in headless/web mode."""
    # Monkey patch the GUI class
    sys.modules['gui'] = sys.modules[__name__]