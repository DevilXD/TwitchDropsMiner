# Event handlers and logging handlers for the WebUI
# Contains all callback functions and logging integration

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class WebUIOutputHandler(logging.Handler):
    """Logging handler that outputs to the web UI"""

    def __init__(self, output: "WebUIManager"):
        super().__init__()
        self._output = output

    def emit(self, record):
        self._output.print(self.format(record))
