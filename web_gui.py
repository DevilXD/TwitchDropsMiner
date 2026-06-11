from __future__ import annotations

import asyncio
import json
import logging
from time import time
from collections import deque
from datetime import datetime
from typing import Any, TYPE_CHECKING

from aiohttp import web

from exceptions import ExitRequest
from utils import _T
from constants import State, WS_TOPICS_LIMIT, OUTPUT_FORMATTER

if TYPE_CHECKING:
    from collections import abc
    from yarl import URL
    from twitch import Twitch
    from channel import Channel
    from settings import Settings
    from inventory import DropsCampaign, TimedDrop
    from constants import JsonType

logger = logging.getLogger("TwitchDrops")

WEB_PORT = 5001
MAX_LOG_MESSAGES = 500


def _coerce_priority_mode(value: Any):
    """Accept a PriorityMode, its int value, or its name string."""
    from constants import PriorityMode
    if isinstance(value, PriorityMode):
        return value
    try:
        if isinstance(value, str) and value in PriorityMode.__members__:
            return PriorityMode[value]
        return PriorityMode(int(value))
    except (ValueError, TypeError, KeyError):
        return None


class _WebOutputHandler(logging.Handler):
    def __init__(self, manager: GUIManager):
        super().__init__()
        self._manager = manager

    def emit(self, record: logging.LogRecord) -> None:
        self._manager.print(self.format(record))


class WebLoginForm:
    def __init__(self, manager: GUIManager):
        self._manager = manager
        self._status: str = "Logged out"
        self._user_id: int | None = None
        self._code: str | None = None
        self._code_url: str | None = None
        self._awaiting_input: bool = False
        self._login_event: asyncio.Event = asyncio.Event()
        self._login_data: dict[str, str] | None = None

    def _state(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "user_id": self._user_id,
            "code": self._code,
            "code_url": self._code_url,
            "waiting_for_input": self._awaiting_input and self._code is None,
        }

    def clear(self, login: bool = False, password: bool = False, token: bool = False) -> None:
        self._login_data = None
        self._manager._broadcast({"type": "login_state", **self._state()})

    async def ask_login(self):
        from dataclasses import dataclass

        @dataclass
        class LoginData:
            username: str
            password: str
            token: str

        self._status = "Login required"
        self._code = None
        self._code_url = None
        self._awaiting_input = True
        self._manager.print("Login required. Please enter your Twitch credentials in the web interface.")
        self._manager._broadcast({"type": "login_state", **self._state()})

        try:
            while True:
                self._login_event.clear()
                self._login_data = None
                await self._manager.coro_unless_closed(self._login_event.wait())
                data = self._login_data or {}
                username = data.get("username", "").strip()
                password = data.get("password", "")
                token = data.get("token", "").strip()

                if not (3 <= len(username) <= 25):
                    self._manager._broadcast({"type": "login_error", "message": "Username must be 3-25 characters"})
                    continue
                if len(password) < 8:
                    self._manager._broadcast({"type": "login_error", "message": "Password must be at least 8 characters"})
                    continue
                if token and len(token) < 6:
                    self._manager._broadcast({"type": "login_error", "message": "2FA token must be at least 6 characters"})
                    continue
                return LoginData(username=username, password=password, token=token)
        finally:
            self._awaiting_input = False
            self._manager._broadcast({"type": "login_state", **self._state()})

    async def ask_enter_code(self, page_url: URL, user_code: str) -> None:
        self._status = "Device activation required"
        self._code = user_code
        self._code_url = str(page_url)
        self._awaiting_input = False
        self._manager.print(
            f"Device activation required. Go to {page_url} and enter code: {user_code}"
        )
        self._manager._broadcast({"type": "login_state", **self._state()})
        # Wait briefly so the UI can update, then return and let Twitch polling take over
        await asyncio.sleep(2)

    def update(self, status: str, user_id: int | None) -> None:
        self._status = status
        self._user_id = user_id
        self._code = None
        self._code_url = None
        self._awaiting_input = False
        self._manager._broadcast({"type": "login_state", **self._state()})

    def submit(self, data: dict[str, str]) -> None:
        self._login_data = data
        self._login_event.set()


class WebStatusBar:
    def __init__(self, manager: GUIManager):
        self._manager = manager
        self._text: str = ""

    def update(self, text: str) -> None:
        self._text = text
        self._manager._broadcast({"type": "status", "text": text})


class WebTrayIcon:
    def __init__(self, manager: GUIManager):
        self._manager = manager
        self._icon: str = "pickaxe"

    def change_icon(self, name: str) -> None:
        self._icon = name
        self._manager._broadcast({"type": "icon", "name": name})

    def restore(self) -> None:
        pass

    def minimize(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def update_title(self, drop: TimedDrop | None) -> None:
        pass

    def notify(self, message: str, title: str = "") -> None:
        self._manager._broadcast({"type": "notification", "title": title, "message": message})


class WebChannelList:
    def __init__(self, manager: GUIManager):
        self._manager = manager
        self._channels: dict[str, dict[str, Any]] = {}
        self._watching_id: str | None = None
        self._selected_id: str | None = None

    def _channel_data(self, channel: Channel) -> dict[str, Any]:
        return {
            "id": channel.iid,
            "name": channel.name,
            "online": channel.online,
            "pending_online": channel.pending_online,
            "offline": channel.offline,
            "game": str(channel.game or ""),
            "drops_enabled": channel.drops_enabled,
            "viewers": channel.viewers,
            "acl_based": channel.acl_based,
            "watching": channel.iid == self._watching_id,
        }

    def display(self, channel: Channel, *, add: bool = False) -> None:
        iid = channel.iid
        data = self._channel_data(channel)
        if iid in self._channels:
            self._channels[iid] = data
            self._manager._broadcast({"type": "channel_update", "channel": data})
        elif add:
            self._channels[iid] = data
            self._manager._broadcast({"type": "channel_add", "channel": data})

    def remove(self, channel: Channel) -> None:
        iid = channel.iid
        self._channels.pop(iid, None)
        if self._watching_id == iid:
            self._watching_id = None
        if self._selected_id == iid:
            self._selected_id = None
        self._manager._broadcast({"type": "channel_remove", "id": iid})

    def clear(self) -> None:
        self._channels.clear()
        self._watching_id = None
        self._selected_id = None
        self._manager._broadcast({"type": "channels_clear"})

    def clear_watching(self) -> None:
        if self._watching_id is not None:
            old_id = self._watching_id
            self._watching_id = None
            if old_id in self._channels:
                self._channels[old_id]["watching"] = False
            self._manager._broadcast({"type": "watching", "channel_id": None})

    def set_watching(self, channel: Channel) -> None:
        old_id = self._watching_id
        self._watching_id = channel.iid
        if old_id and old_id in self._channels:
            self._channels[old_id]["watching"] = False
        if channel.iid in self._channels:
            self._channels[channel.iid]["watching"] = True
        self._manager._broadcast({"type": "watching", "channel_id": channel.iid})

    def get_selection(self) -> Channel | None:
        if self._selected_id is None:
            return None
        twitch = self._manager._twitch
        for channel in twitch.channels.values():
            if channel.iid == self._selected_id:
                return channel
        self._selected_id = None
        return None

    def clear_selection(self) -> None:
        self._selected_id = None

    def set_selection(self, channel_id: str) -> None:
        self._selected_id = channel_id


class WebCampaignProgress:
    # If no progress update has arrived for this long, consider Twitch's
    # progress reporting stalled (a real update should arrive every ~60s).
    STALE_SECONDS = 45

    def __init__(self, manager: GUIManager):
        self._manager = manager
        self._drop: TimedDrop | None = None
        self._last_progress: float = 0.0
        self._timer_task: asyncio.Task[None] | None = None

    def _drop_data(self, drop: TimedDrop, *, subone: bool = False) -> dict[str, Any]:
        campaign = drop.campaign
        remaining_minutes = drop.remaining_minutes
        if subone and remaining_minutes > 0:
            remaining_minutes -= 1
        return {
            "id": drop.id,
            "name": drop.name,
            "rewards": drop.rewards_text(),
            "current_minutes": drop.current_minutes,
            "required_minutes": drop.required_minutes,
            "remaining_minutes": remaining_minutes,
            "progress": drop.progress,
            "campaign": {
                "id": campaign.id,
                "name": campaign.name,
                "game": str(campaign.game),
                "image_url": str(campaign.image_url),
                "claimed_drops": campaign.claimed_drops,
                "total_drops": campaign.total_drops,
                "remaining_minutes": campaign.remaining_minutes,
                "progress": campaign.progress,
                "ends_at": campaign.ends_at.isoformat(),
            },
        }

    def current_state(self) -> dict[str, Any] | None:
        if self._drop is None:
            return None
        return self._drop_data(self._drop)

    def display(
        self, drop: TimedDrop | None, *, countdown: bool = True, subone: bool = False
    ) -> None:
        self._drop = drop
        self._last_progress = time()
        if drop is None:
            self._manager._broadcast({"type": "drop", "drop": None})
            return
        self._manager._broadcast({"type": "drop", "drop": self._drop_data(drop, subone=subone)})
        if countdown and self._timer_task is None:
            self.start_timer()

    def start_timer(self) -> None:
        if self._timer_task is None and self._drop is not None:
            self._timer_task = asyncio.create_task(self._timer_loop())

    def stop_timer(self) -> None:
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    async def _timer_loop(self) -> None:
        # periodic re-broadcast so freshly connected clients stay in sync;
        # intentionally does NOT touch _last_progress, which tracks real updates
        try:
            while self._drop is not None:
                await asyncio.sleep(30)
                if self._drop is not None:
                    self._manager._broadcast(
                        {"type": "drop", "drop": self._drop_data(self._drop)}
                    )
        except asyncio.CancelledError:
            pass
        finally:
            self._timer_task = None

    def minute_almost_done(self) -> bool:
        if self._drop is None:
            # no drop tracked - report stalled so the watch loop runs its fallbacks
            return True
        return time() - self._last_progress >= self.STALE_SECONDS


class WebConsoleOutput:
    def __init__(self, manager: GUIManager):
        self._manager = manager

    def print(self, message: str) -> None:
        self._manager.print(message)


class WebInventoryOverview:
    def __init__(self, manager: GUIManager):
        self._manager = manager
        self._campaign_objects: list[DropsCampaign] = []
        self._claimed_ids: set[str] = set()

    @property
    def _campaigns(self) -> list[dict[str, Any]]:
        return [self._campaign_data(c) for c in self._campaign_objects]

    def clear(self) -> None:
        self._campaign_objects.clear()
        self._manager._broadcast({"type": "campaigns", "campaigns": []})

    def update_drop(self, drop: TimedDrop) -> None:
        if drop.is_claimed and drop.id not in self._claimed_ids:
            self._claimed_ids.add(drop.id)
            campaign = drop.campaign
            entry: dict[str, Any] = {
                "id": drop.id,
                "name": drop.name,
                "rewards": drop.rewards_text(),
                "campaign_name": campaign.name,
                "game": str(campaign.game),
                "image_url": drop.benefits[0].image_url if drop.benefits else "",
                "claimed_at": datetime.utcnow().isoformat() + "Z",
            }
            self._manager._drop_history.insert(0, entry)
            if len(self._manager._drop_history) > 200:
                self._manager._drop_history.pop()
            self._manager._broadcast({"type": "drop_claimed", "drop": entry})
        self._broadcast_campaigns()

    def _campaign_data(self, campaign: DropsCampaign) -> dict[str, Any]:
        drops_data = []
        for drop in campaign.drops:
            drops_data.append({
                "id": drop.id,
                "name": drop.name,
                "rewards": drop.rewards_text(),
                "current_minutes": drop.current_minutes,
                "required_minutes": drop.required_minutes,
                "progress": drop.progress,
                "is_claimed": drop.is_claimed,
                "can_earn": drop.can_earn(),
                "can_claim": drop.can_claim,
                "image_url": drop.benefits[0].image_url if drop.benefits else "",
            })
        return {
            "id": campaign.id,
            "name": campaign.name,
            "game": str(campaign.game),
            "image_url": str(campaign.image_url),
            "linked": campaign.linked,
            "link_url": campaign.link_url,
            "active": campaign.active,
            "upcoming": campaign.upcoming,
            "eligible": campaign.eligible,
            "claimed_drops": campaign.claimed_drops,
            "total_drops": campaign.total_drops,
            "remaining_minutes": campaign.remaining_minutes,
            "progress": campaign.progress,
            "starts_at": campaign.starts_at.isoformat(),
            "ends_at": campaign.ends_at.isoformat(),
            "drops": drops_data,
        }

    def _broadcast_campaigns(self) -> None:
        self._manager._broadcast({"type": "campaigns", "campaigns": self._campaigns})

    async def add_campaign(self, campaign: DropsCampaign) -> None:
        self._campaign_objects.append(campaign)
        self._broadcast_campaigns()


class WebSettingsPanel:
    def __init__(self, manager: GUIManager):
        self._manager = manager
        self._available_games: list[str] = []

    def set_games(self, games: set) -> None:
        self._available_games = sorted(g.name for g in games)
        self._manager._broadcast({
            "type": "available_games",
            "games": self._available_games,
        })

    def clear_selection(self) -> None:
        pass


class WebWebsocketStatus:
    """
    Mirrors gui.WebsocketStatus: websocket.py calls
    update(idx, status=..., topics=...) and remove(idx).
    """

    def __init__(self, manager: GUIManager):
        self._manager = manager
        self._items: dict[int, dict[str, Any]] = {}

    def update(self, idx: int, status: str | None = None, topics: int | None = None) -> None:
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")
        entry = self._items.get(idx)
        if entry is None:
            entry = self._items[idx] = {"status": "Disconnected", "topics": 0}
        if status is not None:
            entry["status"] = status
        if topics is not None:
            entry["topics"] = topics
        self._broadcast()

    def remove(self, idx: int) -> None:
        if idx in self._items:
            del self._items[idx]
            self._broadcast()

    def state(self) -> list[dict[str, Any]]:
        return [
            {
                "id": idx + 1,
                "status": entry["status"],
                "topics": entry["topics"],
                "limit": WS_TOPICS_LIMIT,
            }
            for idx, entry in sorted(self._items.items())
        ]

    def _broadcast(self) -> None:
        self._manager._broadcast({"type": "websockets", "websockets": self.state()})


class GUIManager:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._close_requested = asyncio.Event()
        self._sse_clients: list[asyncio.Queue[str | None]] = []
        self._log_messages: deque[str] = deque(maxlen=MAX_LOG_MESSAGES)
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._poll_task: asyncio.Task[None] | None = None

        self._drop_history: list[dict[str, Any]] = []

        # Sub-components matching the original GUIManager interface
        self.login = WebLoginForm(self)
        self.status = WebStatusBar(self)
        self.tray = WebTrayIcon(self)
        self.channels = WebChannelList(self)
        self.progress = WebCampaignProgress(self)
        self.output = WebConsoleOutput(self)
        self.inv = WebInventoryOverview(self)
        self.settings = WebSettingsPanel(self)
        self.websockets = WebWebsocketStatus(self)

        # Register logging handler
        self._handler = _WebOutputHandler(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logging.getLogger("TwitchDrops").addHandler(self._handler)

    # ------------------------------------------------------------------ #
    # SSE broadcasting
    # ------------------------------------------------------------------ #

    def _broadcast(self, data: dict[str, Any]) -> None:
        msg = f"data: {json.dumps(data)}\n\n"
        for q in list(self._sse_clients):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def _full_state(self) -> dict[str, Any]:
        return {
            "type": "init",
            "status": self.status._text,
            "icon": self.tray._icon,
            "login": self.login._state(),
            "channels": list(self.channels._channels.values()),
            "watching_channel_id": self.channels._watching_id,
            "campaigns": self.inv._campaigns,
            "available_games": self.settings._available_games,
            "settings": self._settings_state(),
            "websockets": self.websockets.state(),
            "drop": self.progress.current_state(),
            "log": list(self._log_messages),
            "history": self._drop_history,
        }

    def _settings_state(self) -> dict[str, Any]:
        s = self._twitch.settings
        return {
            "priority": list(s.priority),
            "exclude": list(s.exclude),
            "priority_mode": s.priority_mode.name,
            "enable_badges_emotes": s.enable_badges_emotes,
            "available_drops_check": s.available_drops_check,
            "connection_quality": s.connection_quality,
            "proxy": str(s.proxy) if s.proxy else "",
        }

    # ------------------------------------------------------------------ #
    # Web server routes
    # ------------------------------------------------------------------ #

    async def _handle_index(self, request: web.Request) -> web.Response:
        import os
        html_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        return web.Response(text=content, content_type="text/html")

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        response.headers["Content-Type"] = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Connection"] = "keep-alive"
        response.headers["Access-Control-Allow-Origin"] = "*"
        await response.prepare(request)

        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=100)
        self._sse_clients.append(queue)

        # Send full state immediately
        init_msg = f"data: {json.dumps(self._full_state())}\n\n"
        try:
            await response.write(init_msg.encode())
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                await response.write(msg.encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._sse_clients.remove(queue)
        return response

    async def _handle_state(self, request: web.Request) -> web.Response:
        return web.json_response(self._full_state())

    async def _handle_login(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        self.login.submit(data)
        return web.json_response({"ok": True})

    async def _handle_select_channel(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            channel_id = str(data.get("channel_id", ""))
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        self.channels.set_selection(channel_id)
        self._twitch.change_state(State.CHANNEL_SWITCH)
        return web.json_response({"ok": True})

    async def _handle_settings(self, request: web.Request) -> web.Response:
        from yarl import URL as YarlURL
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        s = self._twitch.settings
        if "priority" in data:
            s.priority = list(data["priority"])
        if "exclude" in data:
            s.exclude = set(data["exclude"])
        if "priority_mode" in data:
            mode = _coerce_priority_mode(data["priority_mode"])
            if mode is not None:
                s.priority_mode = mode
        if "enable_badges_emotes" in data:
            s.enable_badges_emotes = bool(data["enable_badges_emotes"])
        if "available_drops_check" in data:
            s.available_drops_check = bool(data["available_drops_check"])
        if "connection_quality" in data:
            val = int(data["connection_quality"])
            s.connection_quality = max(1, min(6, val))
        if "proxy" in data:
            s.proxy = YarlURL(data["proxy"]) if data["proxy"] else YarlURL()
        s.save(force=True)
        self._broadcast({"type": "settings", "settings": self._settings_state()})
        return web.json_response({"ok": True})

    async def _handle_settings_import(self, request: web.Request) -> web.Response:
        """
        Accepts an uploaded settings.json file (the same format this app saves),
        merges it into the current settings, saves and broadcasts the result.
        Handles both the app's typed serialization format ("__type" wrappers)
        and plain JSON with simple values.
        """
        from settings import default_settings
        from yarl import URL as YarlURL
        from utils import _deserialize, _remove_missing

        try:
            if request.content_type and request.content_type.startswith("multipart/"):
                reader = await request.multipart()
                raw: str = ""
                async for field in reader:  # type: ignore[union-attr]
                    if field.name == "file":
                        raw = (await field.read(decode=True)).decode("utf8")
                        break
                if not raw:
                    return web.json_response({"error": "No file uploaded"}, status=400)
            else:
                raw = await request.text()
            data = json.loads(raw, object_hook=_deserialize)
            if not isinstance(data, dict):
                raise ValueError("Settings file must contain a JSON object")
            data = _remove_missing(data)
        except Exception as exc:
            return web.json_response({"error": f"Invalid settings file: {exc}"}, status=400)

        # coerce plain JSON values into the proper types
        coercers: dict[str, Any] = {
            "priority": lambda v: [str(x) for x in v] if isinstance(v, list) else None,
            "exclude": lambda v: set(str(x) for x in v) if isinstance(v, (list, set)) else None,
            "priority_mode": _coerce_priority_mode,
            "proxy": lambda v: v if isinstance(v, YarlURL) else YarlURL(str(v or "")),
            "connection_quality": lambda v: max(1, min(6, int(v))),
            "language": lambda v: str(v),
            "dark_mode": lambda v: bool(v),
            "autostart_tray": lambda v: bool(v),
            "tray_notifications": lambda v: bool(v),
            "enable_badges_emotes": lambda v: bool(v),
            "available_drops_check": lambda v: bool(v),
        }
        s = self._twitch.settings
        imported: list[str] = []
        skipped: list[str] = []
        for key, value in data.items():
            if key not in default_settings:
                skipped.append(key)
                continue
            coerce = coercers.get(key)
            if coerce is not None:
                try:
                    value = coerce(value)
                except (ValueError, TypeError):
                    skipped.append(key)
                    continue
                if value is None:
                    skipped.append(key)
                    continue
            try:
                setattr(s, key, value)
                imported.append(key)
            except TypeError:
                skipped.append(key)
        s.save(force=True)
        self._broadcast({"type": "settings", "settings": self._settings_state()})
        self.print(f"Settings imported from uploaded file: {', '.join(imported) or 'nothing'}")
        return web.json_response({"ok": True, "imported": imported, "skipped": skipped})

    async def _handle_settings_export(self, request: web.Request) -> web.Response:
        from utils import _serialize
        body = json.dumps(
            self._twitch.settings._settings, default=_serialize, indent=4, sort_keys=True
        )
        return web.Response(
            text=body,
            content_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="settings.json"'},
        )

    async def _handle_close(self, request: web.Request) -> web.Response:
        self.close()
        return web.json_response({"ok": True})

    async def _handle_reload(self, request: web.Request) -> web.Response:
        self._twitch.change_state(State.INVENTORY_FETCH)
        return web.json_response({"ok": True})

    async def _handle_history(self, request: web.Request) -> web.Response:
        return web.json_response({"history": self._drop_history})

    async def _start_server(self) -> None:
        try:
            await self._start_server_inner()
        except OSError as exc:
            # most likely the port is already in use
            logger.error(f"Failed to start the web server on port {WEB_PORT}: {exc}")
            self.print(f"FATAL: Cannot start web server on port {WEB_PORT}: {exc}")
            self.close()

    async def _start_server_inner(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/events", self._handle_sse)
        self._app.router.add_get("/api/state", self._handle_state)
        self._app.router.add_post("/api/login", self._handle_login)
        self._app.router.add_post("/api/channels/select", self._handle_select_channel)
        self._app.router.add_post("/api/settings", self._handle_settings)
        self._app.router.add_post("/api/settings/import", self._handle_settings_import)
        self._app.router.add_get("/api/settings/export", self._handle_settings_export)
        self._app.router.add_post("/api/close", self._handle_close)
        self._app.router.add_post("/api/reload", self._handle_reload)
        self._app.router.add_get("/api/history", self._handle_history)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", WEB_PORT)
        await self._site.start()
        self.print(f"Web server started on http://0.0.0.0:{WEB_PORT}")

    async def _stop_server(self) -> None:
        for q in list(self._sse_clients):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._app = None

    # ------------------------------------------------------------------ #
    # GUIManager interface matching the original
    # ------------------------------------------------------------------ #

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    async def wait_until_closed(self) -> None:
        await self._close_requested.wait()

    async def coro_unless_closed(self, coro: abc.Awaitable[_T]) -> _T:
        tasks = [
            asyncio.ensure_future(coro),
            asyncio.ensure_future(self._close_requested.wait()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if self._close_requested.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def prevent_close(self) -> None:
        self._close_requested.clear()

    def start(self) -> None:
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._start_server())

    def stop(self) -> None:
        self.progress.stop_timer()
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    def close(self, *args: Any) -> int:
        self._close_requested.set()
        self._twitch.close()
        return 0

    def close_window(self) -> None:
        logging.getLogger("TwitchDrops").removeHandler(self._handler)

    async def close_window_async(self) -> None:
        """Cleanly shut the web server down. Preferred over close_window."""
        self.close_window()
        await self._stop_server()

    def save(self, *, force: bool = False) -> None:
        pass

    def grab_attention(self, *, sound: bool = True) -> None:
        pass

    def set_games(self, games: set) -> None:
        self.settings.set_games(games)

    def display_drop(
        self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False
    ) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)

    def clear_drop(self) -> None:
        self.progress.display(None)

    def print(self, message: str) -> None:
        stamp = datetime.now().strftime("%X")
        if "\n" in message:
            lines = message.split("\n")
            formatted = f"\n{stamp}: ".join(lines)
        else:
            formatted = message
        entry = f"{stamp}: {formatted}"
        self._log_messages.append(entry)
        self._broadcast({"type": "log", "message": entry})
