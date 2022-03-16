from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict, TYPE_CHECKING

from constants import JsonType, SETTINGS_PATH

if TYPE_CHECKING:
    from main import ParsedArgs


PATH = Path(SETTINGS_PATH)


class SettingsFile(TypedDict):
    autostart: bool
    exclude: set[str]
    priority: list[str]
    priority_only: bool
    autostart_tray: bool


serialize_env: dict[str, type] = {
    "set": set,
}
default_settings: SettingsFile = {
    "priority": [],
    "exclude": set(),
    "autostart": False,
    "priority_only": True,
    "autostart_tray": False,
}


def serialize(obj: Any) -> Any:
    if isinstance(obj, (set, Enum)):
        if isinstance(obj, set):
            d = list(obj)
        elif isinstance(obj, Enum):
            d = obj.value
        return {
            "__type": type(obj).__name__,
            "data": d,
        }
    raise TypeError(obj)


def deserialize(obj: JsonType) -> Any:
    if "__type" in obj:
        t = eval(obj["__type"], None, serialize_env)
        return t(obj["data"])
    return obj


class Settings:
    # from args
    log: bool
    tray: bool
    no_run_check: bool
    # args properties
    debug_ws: int
    debug_gql: int
    logging_level: int
    # from settings file
    autostart: bool
    exclude: set[str]
    priority: list[str]
    priority_only: bool
    autostart_tray: bool

    def __init__(self, args: ParsedArgs):
        self._settings: SettingsFile = default_settings.copy()
        if PATH.exists():
            with open(PATH, 'r') as file:
                self._settings.update(json.load(file, object_hook=deserialize))
        self._args: ParsedArgs = args

    # default logic of reading settings is to check args first, then the settings file
    def __getattr__(self, name: str, /) -> Any:
        if hasattr(self._args, name):
            return getattr(self._args, name)
        elif name in self._settings:
            return self._settings[name]  # type: ignore[misc]
        return getattr(super(), name)

    def __setattr__(self, name: str, value: Any, /) -> None:
        if name in ("_settings", "_args"):
            # passthrough
            return super().__setattr__(name, value)
        elif name in self._settings:
            self._settings[name] = value  # type: ignore[misc]
            return
        raise TypeError(f"{name} is missing a custom setter")

    def __delattr__(self, name: str, /) -> None:
        raise RuntimeError("settings can't be deleted")

    def save(self) -> None:
        with open(PATH, 'w') as file:
            json.dump(self._settings, file, default=serialize, sort_keys=True, indent=4)
