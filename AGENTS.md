# TwitchDropsMiner

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
    ├── main_panel.py        # Main tab: thin aggregator, delegates to main/ sections
    ├── inventory_panel.py   # Inventory tab
    ├── settings_panel.py    # Settings tab
    ├── help_panel.py        # Help tab
    ├── main/                # Sub-components of the main tab
    │   ├── channels_section.py  # Channel table (map, rows, per-client instances)
    │   ├── console_section.py   # Console log (persistence, per-client ui.log instances)
    │   ├── drop_section.py      # Drop/campaign progress display and tick timer
    │   ├── login_section.py     # Login status labels and login/logout buttons
    │   └── websocket_section.py # WebSocket status display
    └── settings/            # Sub-components of the settings tab
        ├── game_list_section.py # Abstract base for priority/exclude lists
        ├── general_section.py   # General + advanced settings cards, reload button
        ├── priority_section.py  # Ordered priority list (extends GameListSection)
        └── exclude_section.py   # Exclude set (extends GameListSection)
```

## Architecture Patterns

### Adapter pattern
Each attribute on `GUIManager` (e.g. `self.gui.status`, `self.gui.channels`) has a matching adapter in `webui/adapters/`. Adapters are thin — typically 15-40 lines — and just forward calls to `MainPanel` or `WebUIManager`. When adding support for a new `twitch.py` GUI call, add or extend an adapter rather than touching `twitch.py`.

### Section pattern (main tab)
`MainPanel` is a thin aggregator. Each logical area of the main tab lives in its own section class under `webui/components/main/`. Each section owns both its state and its UI code — they are colocated because NiceGUI's `.bind_*_from` and `@ui.refreshable` both reference `self`. `MainPanel` instantiates the five sections and exposes a public API that delegates to them; external code (adapters, `manager.py`) only calls `MainPanel`'s public methods, never reaching into section internals directly.

Sections and what they own:
| Section | State | Key behaviour |
|---|---|---|
| `ChannelsSection` | channel map, rows, per-client `ui.table` list | rebuilds rows on any channel change |
| `ConsoleSection` | console log, per-client `ui.log` list | pushes lines directly to live log instances (no refresh) |
| `DropSection` | drop/campaign display attrs, countdown timer | manages its own `app.timer` in constructor |
| `LoginSection` | login status text, button visibility | logout button calls `manager.logout()` |
| `WebsocketSection` | ws data dict | refreshable status display |

### Section pattern (settings tab)
`SettingsPanel` is a thin aggregator like `MainPanel`. Its three sections live under `webui/components/settings/`.

`GeneralSection` owns the general card (language, dark mode, priority mode, proxy) and the advanced card (badges/emotes, available-drops-check toggles), plus the reload button. It calls `manager._twitch.state_change(State.INVENTORY_FETCH)` for reload and reloads all connected clients via `ui.run_javascript("location.reload()")` after a language change.

`PrioritySection` and `ExcludeSection` both extend the abstract `GameListSection`, which provides two `@ui.refreshable` methods — `_input_content` (autocomplete input + dropdown + add button) and `_list_content` (selectable list) — shared by both subclasses. Subclasses supply the data model via abstract methods (`_options`, `_items`, `_item_label`, `_is_selected`, `_on_select`, `_on_delete`, `_do_add`). Key difference: `PrioritySection` tracks selection by list index (ordered `list`) and adds reorder buttons; `ExcludeSection` tracks selection by name (unordered `set`) with only a delete button. `GameListSection.set_games()` is called by `SettingsPanel.set_games()` (which `manager.set_games()` calls) to populate autocomplete options; unknown game names trigger a confirmation dialog before adding.

### Shared state on sections
Each section owns its mutable display state as instance variables. This lets late-joining browser clients restore full state on page load without waiting for backend updates. Do not store display state in local scope or per-request objects.

### Per-client element tracking
For elements that must be updated live across all connected clients (channel table, console log), sections keep a list of per-client element instances (e.g. `_channel_tables`, `_log_instances`). Each `build()` call appends the new element and registers an `on_disconnect` handler to remove it.

### Single event loop
Both the NiceGUI UI and the async backend run on NiceGUI's event loop — no thread queues needed. Use `asyncio.create_task()` for background work; use `await ui.run_javascript()` for client-side interactions.

### Logout / session teardown
`logout()` in `manager.py` is webui-only (the tkinter GUI has no logout). It works by racing a signal against the next HTTP request rather than doing teardown itself:

1. `session.cookie_jar.clear()` — empties the in-memory jar so `shutdown()` saves empty cookies to disk, preventing auto-login on restart.
2. `self.channels.clear()` — clears the channel list UI immediately (the adapter-only call; `shutdown()` clears `twitch.py`'s internal dict but doesn't update the UI).
3. `_reload_requested.set()` — arms the signal.
4. `state_change(INVENTORY_FETCH)` — wakes the main loop out of IDLE so it reaches an HTTP call.

`coro_unless_closed()` races every HTTP request against `_reload_requested`. When it fires, `ReloadRequest` is raised and propagates up through `_run()` to `run()`, which calls `shutdown()` (full teardown: stops websockets, closes session, clears all internal state) then restarts `_run()` fresh (re-login flow, new user topics).

Do not add teardown logic to `logout()` that `shutdown()` already handles — it will run redundantly.

### No direct UI calls from backend
`twitch.py` never calls `ui.*` directly. The flow is always:
```
twitch.py → adapter → WebUIManager / MainPanel → section → ui.*
```

## NiceGUI Documentation

When researching NiceGUI v3 APIs, these JSON indexes are available on the docs site and are more useful than the search index alone:

| URL | Contents |
|---|---|
| `https://nicegui.io/static/sitewide_index.json` | Documentation pages with code — no examples (best for learning API syntax) |
| `https://nicegui.io/static/examples_index.json` | Examples only |
| `https://nicegui.io/static/search_index.json` | Minimal index used by the site's search UI |

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
