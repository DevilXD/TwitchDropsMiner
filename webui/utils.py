"""Utility functions for the WebUI."""

from __future__ import annotations

from typing import Any, Callable


def for_each_client(
    client_map: dict[str, Any],
    callback: Callable[[Any], None],
) -> None:
    """
    Execute a callback for each client in the mapping, removing stale clients
    that raise RuntimeError (indicating the NiceGUI client was deleted).
    """
    stale_clients: list[str] = []
    for client_id, obj in list(client_map.items()):
        try:
            callback(obj)
        except RuntimeError:
            stale_clients.append(client_id)
    for client_id in stale_clients:
        client_map.pop(client_id, None)
