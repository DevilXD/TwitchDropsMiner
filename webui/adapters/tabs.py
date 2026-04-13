from __future__ import annotations


class TabsAdapter:
    """
    Mirrors the tkinter tab controller (Notebook).

    twitch.py uses current_tab() to read the active tab index and
    add_view_event() to register a callback when the tab changes.  Neither is
    meaningful for the web UI (tab state lives in the browser), so both are
    stubs.  current_tab() returns 0 (the Main tab) as a safe default.
    """

    def current_tab(self) -> int:
        return 0

    def add_view_event(self, callback):
        pass
