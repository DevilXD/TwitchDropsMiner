# TwitchDropsMiner – CLAUDE.md

## Project Overview

TwitchDropsMiner automates watching Twitch streams to earn time-limited drop campaigns. It polls stream metadata only — no video is downloaded — making it very bandwidth-efficient.

This repository is a fork of [DevilXD/TwitchDropsMiner](https://github.com/DevilXD/TwitchDropsMiner). The `webui` branch adds a browser-based UI (NiceGUI) as a drop-in replacement for the original tkinter desktop GUI.

## Key Rule: Minimize Changes Outside `webui/`

**Do not modify files outside the `webui/` folder unless strictly necessary.** The goal is to keep the fork's diff against upstream as small as possible so future merges from `upstream/master` remain easy. If a change to a core file is unavoidable, make it minimal and note why.

Files that should almost never be touched:
- `twitch.py` — core business logic (~2200 lines, the heart of the app)
- `gui.py` / `main.py` — tkinter GUI and its entry point
- `channel.py`, `inventory.py`, `websocket.py`, `settings.py`, `constants.py`

## Entry Points

| Command | Backend |
|---|---|
| `python main.py` | tkinter desktop GUI (original) |
| `python main_webui.py` | NiceGUI web UI (this fork's addition) |

## How the WebUI Connects to the Core App

`twitch.py` does `from gui import GUIManager` — it has no knowledge of NiceGUI. `main_webui.py` injects a stub module before importing `twitch.py`:

```python
# main_webui.py
import types as _types
from webui import WebUIManager as _WebUIManager
_gui_stub = _types.ModuleType('gui')
_gui_stub.GUIManager = _WebUIManager
sys.modules['gui'] = _gui_stub
```

This means `WebUIManager` must implement the same interface as the original `GUIManager` (same attributes and method signatures). When `twitch.py` calls `self.gui.status.update(...)`, it hits the webui adapter layer transparently.

## `webui/` Folder Layout

```
webui/
├── __init__.py              # Exports WebUIManager
├── manager.py               # Top-level WebUIManager class
├── handlers.py              # Python logging → browser console bridge
├── html_utils.py            # JS helpers (favicon, popup windows)
├── adapters/                # Thin forwarding layer (one file per GUI attribute)
│   ├── tray_icon.py         # No-op (no system tray in browser)
│   ├── status_bar.py        # Forwards to manager.update_status()
│   ├── campaign_progress.py # Forwards to main_panel.display_drop()
│   ├── console_output.py    # Forwards to manager.print()
│   ├── channel_list.py      # Forwards to main_panel channel methods
│   ├── inventory_overview.py# Forwards to main_panel inventory methods
│   ├── login_form.py        # Device-code OAuth flow with popup window
│   ├── websocket_status.py  # Updates main_panel websocket data
│   ├── settings.py          # No-op stubs
│   └── tabs.py              # No-op stubs
└── components/              # NiceGUI panels (one per tab)
    ├── base_panel.py        # Abstract base
    ├── header_bar.py        # Fixed header with tabs and status indicator
    ├── main_panel.py        # Main tab: channel table, drop progress, console
    ├── inventory_panel.py   # Inventory tab
    ├── settings_panel.py    # Settings tab
    └── help_panel.py        # Help tab
```

## Architecture Patterns

### Adapter pattern
Each attribute on `GUIManager` (e.g. `self.gui.status`, `self.gui.channels`) has a matching adapter in `webui/adapters/`. Adapters are thin — typically 15-40 lines — and just forward calls to `MainPanel` or `WebUIManager`. When adding support for a new `twitch.py` GUI call, add or extend an adapter rather than touching `twitch.py`.

### Shared state on `MainPanel`
`MainPanel` owns all mutable display state (`_channel_rows`, `_console_log`, etc.) as instance variables. This lets late-joining browser clients restore full state on page load without waiting for backend updates. Do not store display state in local scope or per-request objects.

### Single event loop
Both the NiceGUI UI and the async backend run on NiceGUI's event loop — no thread queues needed. Use `asyncio.create_task()` for background work; use `await ui.run_javascript()` for client-side interactions.

### No direct UI calls from backend
`twitch.py` never calls `ui.*` directly. The flow is always:
```
twitch.py → adapter → WebUIManager / MainPanel → ui.*
```

## Dependencies

```
requirements.txt           # Core: aiohttp, truststore
requirements-tkinter.txt   # Adds: Pillow (for tkinter GUI)
requirements-nicegui.txt   # Adds: nicegui
```

NiceGUI version: **v3.x** (pinned to `<4.0.0` — NiceGUI v4 will have breaking changes).

## Branch Strategy

- `webui` — this fork's main branch (also the GitHub default branch)
- `upstream/master` — upstream DevilXD repo; periodically merged in
- Keep `webui` diff small so upstream merges stay clean

## What _Not_ To Do

- Don't add comments that restate what the code does — only comment non-obvious *why*.
- Don't refactor core files (`twitch.py`, etc.) for style or structure.
- Don't introduce abstractions beyond what the immediate task requires.
- Don't add error handling for scenarios that can't happen in normal operation.
