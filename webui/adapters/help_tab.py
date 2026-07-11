from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class HelpTabAdapter:
    """
    Mirrors the tkinter HelpTab.

    twitch.py accesses ``gui.help._invalidate_button.config(state=...)`` to
    enable/disable the token-invalidation button after login/logout.  The webui
    has no such button (logout triggers token revocation directly), so
    ``config`` is a no-op.  ``_invalidate_button`` points to ``self`` so the
    attribute access chain from twitch.py resolves without error.
    """

    def __init__(self, manager: "WebUIManager"):
        self._manager = manager
        self._invalidate_button = self

    def config(self, *, state: str | None = None, **kwargs):
        pass
