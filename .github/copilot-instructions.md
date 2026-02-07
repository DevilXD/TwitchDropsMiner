# AI Coding Agent Instructions — TwitchDropsMinerWeb

## Project Overview

**Repository**: `Kaysharp42/TwitchDropsMinerWeb`
**Upstream**: `DevilXD/TwitchDropsMiner`
**Language**: Python 3.10+
**Version**: See `version.py`

TwitchDropsMinerWeb is a fork of DevilXD's Twitch Drops Miner that adds a **web-based dashboard** and **Docker support** for headless/server deployment. It automates watching Twitch streams to claim drop rewards via the Twitch GQL API and PubSub websockets.

### What Makes This Fork Different

| Feature | Upstream (DevilXD) | This Fork |
|---|---|---|
| GUI | Tkinter desktop only | Tkinter desktop **+** Web dashboard |
| Deployment | Windows/Linux desktop | Desktop **+** Docker containers |
| Entry point | `main.py` | `main.py` (desktop) / `docker_main.py` (headless) |
| Headless mode | Not supported | Full headless with stub GUI objects |

---

## Architecture

### Dual-Mode Design

The application runs in two modes controlled by `settings.gui_enabled`:

```
┌─────────────────────────────────────────────────┐
│                  twitch.py (core)                │
│         Twitch ← GQL API + PubSub WS            │
│                                                  │
│   gui_enabled=True        gui_enabled=False      │
│   ┌─────────────┐        ┌──────────────────┐   │
│   │  gui.py      │        │ headless_gui.py   │   │
│   │  (tkinter)   │        │ (stub objects)    │   │
│   │  main.py     │        │ docker_main.py    │   │
│   └─────────────┘        │ + web/app.py      │   │
│                           │   (Flask API)     │   │
│                           └──────────────────┘   │
└─────────────────────────────────────────────────┘
```

### Module Graph

| Module | Responsibility |
|---|---|
| `twitch.py` | Core engine: auth, GQL requests, state machine, channel watching, drop claiming |
| `gui.py` | Tkinter desktop GUI (GUIManager, TrayIcon, tabs, status bar) |
| `headless_gui.py` | Dummy GUI stubs for headless mode (DummyGUI, DummyProgress, DummyChannels, DummyStatus, DummyTray) |
| `channel.py` | Channel model: online/offline tracking, stream state, points mining |
| `inventory.py` | Drop campaign models: DropsCampaign, TimedDrop, Benefit, Game, `_on_state_changed()` |
| `settings.py` | Settings proxy with JSON persistence, `gui_enabled` flag |
| `constants.py` | Enums (State, GQLOperation), URLs, websocket topics, GQL templates |
| `websocket.py` | WebsocketPool for Twitch PubSub connections |
| `utils.py` | Helpers: `task_wrapper()`, `ExponentialBackoff`, `OrderedSet` |
| `exceptions.py` | MinerException, CaptchaRequired, LoginException hierarchy |
| `cache.py` | Local image/data caching |
| `translate.py` | i18n system loading from `lang/*.json` |
| `version.py` | Version string |
| `docker_main.py` | Docker/headless entry point: patches GUI, starts Flask, runs Twitch client |
| `web/app.py` | Flask REST API: dashboard, status, campaigns, channels, inventory, settings |
| `web/auth.py` | JWT + Argon2 authentication with `credentials.json` |

### Core State Machine (`twitch.py`)

```
IDLE → INVENTORY_FETCH → GAMES_UPDATE → CHANNELS_CLEANUP
  → CHANNELS_FETCH → CHANNEL_SWITCH → (watching) → IDLE ...
```

States are defined in `constants.py` as the `State` enum. The main loop in `Twitch.run()` processes state transitions. `_state_change()` drives the FSM.

### Critical Tasks

Two asyncio tasks are decorated with `@task_wrapper(critical=True)`:

- **`_watch_loop()`** — Sends "minute watched" events every ~20s to maintain drop progress
- **`_maintenance_task()`** — Periodic inventory refresh and state maintenance

When a critical task crashes with an unhandled exception, the entire application shuts down. **Never let exceptions escape these methods.**

### WebSocket Architecture

`WebsocketPool` in `websocket.py` manages multiple PubSub connections to Twitch. Each connection handles up to N topic subscriptions. Events flow:

```
Twitch PubSub → WebsocketPool → Twitch._handle_event() → state updates / drop claims
```

### Authentication Flow

1. OAuth device code flow via Twitch GQL
2. Access token stored in `settings.json`
3. Token refresh handled automatically
4. Web dashboard has its own separate auth (JWT + Argon2) in `web/auth.py`

---

## Critical Patterns

### 1. GUI-Safety (MOST IMPORTANT)

**Every access to `self.gui.*` or `self._twitch.gui.*` MUST be guarded.**

In headless mode, `self.gui` can be `None` or a stub object. Accessing real GUI methods without a guard crashes the critical `_watch_loop` task and kills the container.

```python
# CORRECT — always guard GUI access
if self.gui_enabled:
    self.gui.status.update("Mining...")

# CORRECT — in inventory.py or other models
if self._twitch.gui_enabled and self._twitch.gui.inv is not None:
    self._twitch.gui.inv.update_drop(drop)

# WRONG — will crash in headless mode
self.gui.status.update("Mining...")  # AttributeError: 'NoneType'
```

**After upstream syncs**: Search for ALL new `self.gui.` references and add guards.

### 2. Headless Patching (`headless_gui.py`)

`apply_headless_patches()` monkey-patches `sys.modules['gui']` so that `from gui import *` imports resolve to stub classes. Called early in `docker_main.py` before any other imports.

Stub classes (DummyGUI, DummyProgress, DummyChannels, DummyStatus, DummyTray) implement no-op methods matching the real GUI interface. When upstream adds new GUI methods, **stubs must be updated**.

### 3. `task_wrapper()` (`utils.py`)

Wraps async coroutines with error handling. When `critical=True`, unhandled exceptions trigger application shutdown. Use this pattern:

```python
@task_wrapper(critical=True)
async def _watch_loop(self):
    # Any unhandled exception here kills the app
    ...
```

### 4. Exception Control Flow

`MinerException` is used for **control flow**, not just errors. `raise MinerException(...)` can signal state transitions. Don't add broad `except Exception` blocks that swallow these.

### 5. Settings Proxy (`settings.py`)

Settings are accessed via a proxy object. Changes auto-persist to `data/settings.json`. Key settings:
- `settings.gui_enabled` — True for desktop, False for Docker/headless
- `settings.autostart` — Auto-start watching on launch
- `settings.priority` / `settings.priority_only` — Game prioritization

### 6. Translations (`translate.py`)

All user-facing strings go through the translation system. Language files are in `lang/*.json`. Use `_()` for translated strings.

### 7. JSON Serialization

Campaign/drop/game data uses custom `from_json()` / `to_json()` class methods with strict key expectations. When upstream changes GQL response shapes, these deserializers must be updated.

---

## Web Interface

### Flask API (`web/app.py`)

The web dashboard runs on port 8080 (configurable). Key endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard HTML |
| `/api/status` | GET | Current miner status (state, uptime, drops) |
| `/api/campaigns` | GET | Active drop campaigns |
| `/api/channels` | GET | Watched/available channels |
| `/api/inventory` | GET | User's drop inventory |
| `/api/settings` | GET/POST | Read/update settings |
| `/api/games` | GET | Tracked games list |
| `/login` | GET/POST | Web login page |
| `/device-login` | GET | Twitch device login flow |

### Auth System (`web/auth.py`)

- First-run setup creates credentials in `data/credentials.json`
- Passwords hashed with Argon2
- JWT tokens for session management
- Token blacklist for logout

### Static Files

- `web/static/css/` — Stylesheets
- `web/static/js/` — Frontend JavaScript
- `web/static/images/`, `web/static/img/` — Assets
- `web/templates/` — Jinja2 HTML templates

---

## Docker Infrastructure

### Container Stack

```yaml
# docker-compose.yml
services:
  twitchdrops:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data    # Persistent storage
    environment:
      - JWT_SECRET=...
```

### Dockerfile

Multi-stage build. Final image runs `docker_main.py` via `docker-entrypoint.sh`.

### Data Persistence

Everything persists under `/data` volume:
- `settings.json` — App settings
- `credentials.json` — Web auth credentials
- `cookies.jar` — Twitch session cookies

### Environment Variables

| Variable | Description |
|---|---|
| `JWT_SECRET` | Secret for JWT token signing |
| `TZ` | Timezone (e.g., `America/New_York`) |

### Helper Scripts

- `generate_jwt_secret.py` / `.bat` / `.sh` — Generate JWT_SECRET value
- `docker-setup.ps1` / `docker-setup.sh` — One-click Docker setup
- `docker-entrypoint.sh` — Container entry point

---

## File Reference

| File | Lines (approx) | Key Contents |
|---|---|---|
| `twitch.py` | ~2200 | Core engine, state machine, GQL, PubSub handling |
| `gui.py` | ~1800 | Tkinter GUI (desktop mode only) |
| `web/app.py` | ~1450 | Flask REST API |
| `channel.py` | ~600 | Channel model |
| `inventory.py` | ~800 | Campaign/drop/benefit models |
| `settings.py` | ~400 | Settings proxy + persistence |
| `constants.py` | ~700 | Enums, URLs, GQL operations |
| `websocket.py` | ~500 | PubSub websocket pool |
| `utils.py` | ~300 | task_wrapper, backoff, helpers |
| `headless_gui.py` | ~110 | Headless GUI stubs |
| `docker_main.py` | ~200 | Docker entry point |
| `web/auth.py` | ~250 | JWT + Argon2 auth |
| `translate.py` | ~150 | i18n system |
| `exceptions.py` | ~50 | Exception hierarchy |

---

## Upstream Sync Notes

### Workflow

```bash
git fetch upstream
git checkout -b sync/upstream-sync master
git merge upstream/master
# Resolve conflicts, then:
# 1. Search for new self.gui.* references — add guards
# 2. Check for new GUI methods — add stubs to headless_gui.py
# 3. Check inventory.py _on_state_changed() — guard gui.inv access
# 4. Test in Docker: docker-compose up --build
git checkout master && git merge sync/upstream-sync
```

### Post-Sync Checklist

- [ ] All new `self.gui.*` accesses guarded with `if self.gui_enabled:`
- [ ] `headless_gui.py` stubs match any new GUI methods
- [ ] `inventory.py` `_on_state_changed()` guards `gui.inv` access
- [ ] No bare `status_update` variable — use `self.gui.status.update()` with guard
- [ ] `docker-compose up --build` runs without crash
- [ ] Web dashboard endpoints return correct data
- [ ] Drop progress tracking works in headless mode

### Common Post-Sync Errors

| Error | Cause | Fix |
|---|---|---|
| `'NoneType' has no attribute 'X'` | Unguarded `self.gui.X` in headless | Add `if self.gui_enabled:` guard |
| `NameError: 'status_update' not defined` | Upstream uses local var | Replace with `self.gui.status.update()` + guard |
| `'NoneType' has no attribute 'inv'` | `_on_state_changed()` gui access | Guard with `self._twitch.gui_enabled` check |
| Container exits immediately | Critical task exception | Check logs, find unguarded GUI access |

---

## Development Commands

```bash
# Desktop mode
python main.py

# Docker
docker-compose up --build

# Build executable (Windows)
build.bat --nopause

# Build + pack
pack.bat

# Setup virtual environment
setup_env.bat          # Windows
./setup_env.sh         # Linux

# Generate JWT secret
python generate_jwt_secret.py

# Run dev mode
run_dev.bat
```

---

## Coding Conventions

1. **Always guard GUI access** — `if self.gui_enabled:` before any `self.gui.*`
2. **Never let exceptions escape critical tasks** — `_watch_loop` and `_maintenance_task` must catch all
3. **Use `MinerException` for control flow** — don't swallow it with broad `except`
4. **`current_minutes` is read-only** — it's a `@property` in `TimedDrop`, never assign to it
5. **Respect the state machine** — don't bypass `_state_change()`, use proper state transitions
6. **Test in Docker after changes** — headless mode is the primary deployment target for this fork
7. **Keep headless stubs in sync** — when upstream adds GUI methods, update `headless_gui.py`
8. **Persist data under `/data`** — Docker volume mount, never write to app directory
9. **Use `asyncio` properly** — the core is async; blocking calls break the event loop
10. **Follow upstream conventions** — this is a fork; minimize divergence to ease future syncs
