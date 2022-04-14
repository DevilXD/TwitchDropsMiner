from __future__ import annotations

from typing import Any, TypedDict, TYPE_CHECKING

from yarl import URL

from constants import SETTINGS_PATH
from utils import json_load, json_save

if TYPE_CHECKING:
    from main import ParsedArgs


class SettingsFile(TypedDict):
    proxy: URL
    autostart: bool
    exclude: set[str]
    priority: list[str]
    priority_only: bool
    autostart_tray: bool


default_settings: SettingsFile = {
    "proxy": URL(),
    "priority": [],
    "exclude": set(),
    "autostart": False,
    "priority_only": False,
    "autostart_tray": False,
}


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
    proxy: URL
    autostart: bool
    exclude: set[str]
    priority: list[str]
    priority_only: bool
    autostart_tray: bool

    def __init__(self, args: ParsedArgs):
        self._settings: SettingsFile = json_load(SETTINGS_PATH, default_settings)
        self._args: ParsedArgs = args
        self._altered: bool = False

    # default logic of reading settings is to check args first, then the settings file
    def __getattr__(self, name: str, /) -> Any:
        if hasattr(self._args, name):
            return getattr(self._args, name)
        elif name in self._settings:
            return self._settings[name]  # type: ignore[literal-required]
        return getattr(super(), name)

    def __setattr__(self, name: str, value: Any, /) -> None:
        if name in ("_settings", "_args"):
            # passthrough
            return super().__setattr__(name, value)
        elif name in self._settings:
            self._settings[name] = value  # type: ignore[literal-required]
            self._altered = True
            return
        raise TypeError(f"{name} is missing a custom setter")

    def __delattr__(self, name: str, /) -> None:
        raise RuntimeError("settings can't be deleted")

    def save(self) -> None:
        if self._altered:
            json_save(SETTINGS_PATH, self._settings)
