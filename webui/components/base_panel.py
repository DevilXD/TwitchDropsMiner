from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class BasePanel(ABC):
    def __init__(self, manager: 'WebUIManager'):
        self._manager = manager

    @abstractmethod
    def build(self) -> None:
        """Build the panel UI for the current NiceGUI client."""
        ...
