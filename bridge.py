"""
Browser bridge: gets a web-client auth token and integrity tokens out of the user's own browser.

Twitch only returns the drop campaigns list to the web client, and only with a `Client-Integrity`
token minted by its anti-bot script, which has to run inside a real browser. Instead of embedding
or automating a browser, the miner serves a small setup page on 127.0.0.1 with a bookmarklet.

1. The user drags the bookmarklet to their bookmarks bar once.
2. Clicking it on www.twitch.tv mints an integrity token, the same way the site itself does,
   and sends it to this server together with the site's auth token and device ID.
3. Whenever the miner needs a new token, it opens www.twitch.tv in the default browser
   and asks the user to click the bookmarklet again. The GUI also has a "Refresh token" button.

Tokens are only accepted by Twitch when minted on a www.twitch.tv page, so this can't be done
from a page served by this server (tested: Twitch answers "failed integrity check").

If the browser refuses to let twitch.tv talk to 127.0.0.1 directly, the bookmarklet falls back
to a small popup served by this server, which relays the token via postMessage and closes itself.

Security:
• the server only binds to the loopback interface
• requests with a Host header other than the loopback address are rejected (DNS rebinding)
• the bookmarklet authenticates with a key that's only embedded into it,
  and CORS only allows https://www.twitch.tv to read responses
• the popup fallback authenticates with a per-run nonce embedded into the popup page,
  and only accepts messages from the www.twitch.tv window that opened it
"""

from __future__ import annotations

import json
import asyncio
import logging
import secrets
from html import escape
from urllib.parse import quote
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from aiohttp import web

from constants import ClientType

if TYPE_CHECKING:
    from twitch import Twitch


logger = logging.getLogger("TwitchDrops")

BRIDGE_HOST = "127.0.0.1"
TWITCH_ORIGIN = "https://www.twitch.tv"


@dataclass
class BridgeCredentials:
    auth_token: str
    device_id: str | None
    user_agent: str
    client_version: str | None
    integrity_token: str
    integrity_expires: datetime
    received_at: datetime


class BridgeRejected(Exception):
    pass


# Runs in the www.twitch.tv tab. Placeholders in double underscores are substituted.
# Kept free of "//" comments, since it's collapsed into a single-line javascript: URL.
BOOKMARKLET_JS = """
(async () => {
    const B = "__BRIDGE_ORIGIN__";
    const KEY = "__KEY__";
    if (location.origin !== "https://www.twitch.tv") {
        alert("Open https://www.twitch.tv first, then click this bookmark again.");
        return;
    }
    const toast = (text, ok) => {
        const d = document.createElement("div");
        d.textContent = text;
        d.style.cssText = "position:fixed;z-index:2147483647;top:16px;left:50%;"
            + "transform:translateX(-50%);padding:10px 16px;border-radius:6px;"
            + "font:600 14px system-ui,sans-serif;color:#fff;box-shadow:0 4px 16px #0006;"
            + "background:" + (ok ? "#9146ff" : "#e91916");
        document.body.appendChild(d);
        setTimeout(() => d.remove(), 5000);
    };
    const cookie = (n) => {
        const m = document.cookie.match("(?:^|; )" + n + "=([^;]*)");
        return m ? decodeURIComponent(m[1]) : null;
    };
    const mint = async () => {
        const auth = cookie("auth-token");
        if (!auth) {
            return { type: "error", error: "You're not logged in to Twitch in this browser." };
        }
        if (window.KPSDK && !window.KPSDK.isReady()) {
            await new Promise((r) => {
                document.addEventListener("kpsdk-ready", r, { once: true });
                setTimeout(r, 10000);
            });
        }
        const device = cookie("unique_id");
        const headers = { "Client-Id": "__CLIENT_ID__", "Authorization": "OAuth " + auth };
        if (device) headers["X-Device-Id"] = device;
        const version = window.__twilightBuildID || null;
        if (version) headers["Client-Version"] = version;
        const r = await fetch("https://gql.twitch.tv/integrity", { method: "POST", headers });
        const text = await r.text();
        let j = null;
        try { j = JSON.parse(text); } catch (e) {}
        if (!j || !j.token) {
            return { type: "error", error: "Integrity HTTP " + r.status + ": " + text.slice(0, 300) };
        }
        return {
            type: "token",
            auth_token: auth,
            device_id: device,
            user_agent: navigator.userAgent,
            client_version: version,
            integrity_token: j.token,
            expiration: j.expiration,
        };
    };
    let res;
    try { res = await mint(); } catch (x) { res = { type: "error", error: String(x) }; }
    if (res.type === "error") {
        toast("Drops Miner: " + res.error);
        return;
    }
    let r;
    try {
        r = await fetch(B + "/api/token", {
            method: "POST",
            cache: "no-store",
            headers: { "X-Bridge-Key": KEY, "Content-Type": "application/json" },
            body: JSON.stringify(res),
        });
    } catch (e) {
        const w = window.open(B + "/popup", "tdm-bridge", "popup,width=420,height=260");
        if (!w) {
            toast("Drops Miner: allow popups for twitch.tv, then click the bookmark again.");
            return;
        }
        const relay = (e) => {
            if (e.origin !== B || e.source !== w || !e.data || e.data.type !== "ready") return;
            window.removeEventListener("message", relay);
            w.postMessage(res, B);
        };
        window.addEventListener("message", relay);
        return;
    }
    let j = {};
    try { j = await r.json(); } catch (e) {}
    if (r.ok) toast("Connected to Twitch Drops Miner. You can close this tab.", true);
    else toast("Drops Miner: " + (j.error || "HTTP " + r.status));
})();
"""

PAGE_STYLE = """
:root { color-scheme: light dark; --bg: #f7f7f8; --fg: #1f1f23; --muted: #53535f;
  --card: #fff; --line: #dedee3; --accent: #9146ff; --ok: #00a67e; --bad: #e91916; }
@media (prefers-color-scheme: dark) { :root { --bg: #0e0e10; --fg: #efeff1; --muted: #adadb8;
  --card: #18181b; --line: #2f2f35; --accent: #bf94ff; --ok: #00f593; --bad: #ff8280; } }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 640px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  padding: 16px; margin: 16px 0; }
.muted { color: var(--muted); }
a { color: var(--accent); }
ol { padding-left: 20px; margin: 0; }
li { margin: 10px 0; }
.drag { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 8px 0; }
.bm { display: inline-block; padding: 10px 18px; border-radius: 6px; background: var(--accent);
  color: #fff; font-weight: 600; text-decoration: none; cursor: grab; user-select: none; }
.bm.shake { animation: shake .4s; }
@keyframes shake { 25% { transform: translateX(-6px); } 75% { transform: translateX(6px); } }
kbd { border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px;
  padding: 0 5px; font: 13px ui-monospace, monospace; }
button { font: inherit; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--line);
  background: var(--card); color: var(--fg); cursor: pointer; }
#status b.ok { color: var(--ok); } #status b.bad { color: var(--bad); }
"""

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect Drops Miner</title><style>__STYLE__</style></head>
<body><main>
<h1>Connect Twitch Drops Miner</h1>
<p class="muted">Twitch only shows the full campaign list to its website, so the miner borrows
your browser's Twitch session through a bookmark. Nothing to install, and your password
never leaves Twitch.</p>
<div class="card" id="status">Status: <b>checking…</b></div>
<div class="card">
<ol>
  <li><b>Drag this button onto your bookmarks bar</b> (one time only):
    <div class="drag">
      <a class="bm" id="bm" href="__BOOKMARKLET__" draggable="true">Connect Drops Miner</a>
      <span class="muted" id="hint">Bookmarks bar hidden? Press <kbd id="kbd">Ctrl+Shift+B</kbd></span>
    </div>
  </li>
  <li><a href="https://www.twitch.tv/" target="_blank" rel="noopener">Open twitch.tv</a>
    and log in with the account you want to mine on.</li>
  <li>On twitch.tv, click <b>Connect Drops Miner</b> in your bookmarks bar.</li>
</ol>
<p class="muted" style="margin-bottom:0">When the miner needs a new token, it opens twitch.tv
for you. Click the bookmark there again, then you can close the tab.</p>
</div>
<p class="muted">Can't drag? <button id="copy">Copy bookmark address</button> then create a
bookmark named "Connect Drops Miner" and paste it as the URL.</p>
</main>
<script>
const bm = document.getElementById("bm");
if (/Mac|iPhone|iPad/.test(navigator.platform)) document.getElementById("kbd").textContent = "\\u2318\\u21e7B";
bm.addEventListener("click", (e) => {
  e.preventDefault();
  bm.classList.remove("shake"); void bm.offsetWidth; bm.classList.add("shake");
  document.getElementById("hint").innerHTML = "<b>Drag</b> it onto your bookmarks bar instead of clicking it here.";
});
document.getElementById("copy").addEventListener("click", async (e) => {
  await navigator.clipboard.writeText(bm.getAttribute("href"));
  e.target.textContent = "Copied";
});
const el = document.getElementById("status");
async function poll() {
  try {
    const s = await (await fetch("/api/state", { cache: "no-store" })).json();
    if (s.connected) {
      el.innerHTML = "Status: <b class='ok'>connected</b>, token valid until " + s.expires_local;
    } else if (s.error) {
      el.innerHTML = "Status: <b class='bad'></b>";
      el.querySelector("b").textContent = s.error;
    } else {
      el.innerHTML = "Status: <b class='bad'>waiting for you to click the bookmark on twitch.tv</b>";
    }
  } catch (e) {
    el.innerHTML = "Status: <b class='bad'>the miner isn't running</b>";
  }
}
poll(); setInterval(poll, 3000);
</script>
</body></html>
"""

# Fallback for browsers that don't let twitch.tv reach 127.0.0.1: relays one token, then closes.
POPUP_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connecting Drops Miner</title><style>__STYLE__</style></head>
<body><main><div class="card" id="status">Getting a token from Twitch…</div></main>
<script>
const NONCE = "__NONCE__";
const TWITCH = "__TWITCH_ORIGIN__";
const statusEl = document.getElementById("status");
function show(text, ok) {
  statusEl.innerHTML = "<b></b>";
  statusEl.firstChild.className = ok ? "ok" : "bad";
  statusEl.firstChild.textContent = text;
}
window.addEventListener("message", async (e) => {
  if (e.origin !== TWITCH || e.source !== window.opener || !e.data) return;
  let r;
  try {
    r = await fetch("/api/token", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Bridge-Nonce": NONCE },
      body: JSON.stringify(e.data),
    });
  } catch (x) {
    return show("The miner isn't running.", false);
  }
  let j = {};
  try { j = await r.json(); } catch (x) {}
  if (!r.ok) return show(j.error || "The miner refused the token (HTTP " + r.status + ").", false);
  show("Connected. This window closes by itself.", true);
  setTimeout(() => window.close(), 1500);
});
if (window.opener) window.opener.postMessage({ type: "ready" }, TWITCH);
else show("Open twitch.tv and click the bookmark there.", false);
</script>
</body></html>
"""


def build_bookmarklet(port: int, key: str) -> str:
    code = (
        BOOKMARKLET_JS
        .replace("__BRIDGE_ORIGIN__", f"http://{BRIDGE_HOST}:{port}")
        .replace("__KEY__", key)
        .replace("__CLIENT_ID__", ClientType.WEB.CLIENT_ID)
    )
    # collapse into a single line
    code = " ".join(line.strip() for line in code.strip().splitlines())
    return code


class TokenBridge:
    def __init__(self, twitch: Twitch, port: int, key: str):
        self._twitch = twitch
        self.port: int = port
        # persistent, since it's baked into the user's bookmark
        self._key: str = key
        # per-run, for the popup fallback
        self._nonce: str = secrets.token_urlsafe(24)
        self._runner: web.AppRunner | None = None
        self._delivered = asyncio.Event()
        self._last_error: str | None = None
        self._prompted: bool = False
        self.credentials: BridgeCredentials | None = None

    @property
    def url(self) -> str:
        return f"http://{BRIDGE_HOST}:{self.port}/"

    @property
    def origin(self) -> str:
        return f"http://{BRIDGE_HOST}:{self.port}"

    async def start(self) -> None:
        if self._runner is not None:
            return
        app = web.Application(middlewares=[self._guard])
        app.router.add_get("/", self._index)
        app.router.add_get("/popup", self._popup)
        app.router.add_get("/api/state", self._state)
        app.router.add_post("/api/token", self._token)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, BRIDGE_HOST, self.port)
        try:
            await site.start()
        except OSError:
            await runner.cleanup()
            raise
        self._runner = runner
        logger.info(f"Browser bridge listening on {self.url}")

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    # Token state

    def integrity_valid(self, margin: timedelta = timedelta(minutes=1)) -> bool:
        creds = self.credentials
        return (
            creds is not None
            and creds.integrity_expires - margin > datetime.now(timezone.utc)
        )

    def invalidate_integrity(self) -> None:
        """Call when Twitch rejected the current integrity token."""
        if self.credentials is not None:
            self.credentials.integrity_expires = datetime.now(timezone.utc)
        self._delivered.clear()

    async def wait_for_token(self) -> None:
        """Wait until the browser delivers a new token."""
        self._delivered.clear()
        await self._delivered.wait()

    def prompt_user(self, *, setup: bool, force: bool = False) -> None:
        """
        Opens the setup page (first login), or twitch.tv (renewal) in the default browser,
        once per missing token, unless forced.
        """
        from utils import webopen

        if force or not self._prompted:
            self._prompted = True
            url = self.url if setup else TWITCH_ORIGIN
            logger.info(f"Opening {url} in the browser for a new token")
            webopen(url)

    # HTTP handlers

    @web.middleware
    async def _guard(self, request: web.Request, handler: Any) -> web.StreamResponse:
        # protect against DNS rebinding: only accept requests addressed to the loopback address
        if request.host not in (f"{BRIDGE_HOST}:{self.port}", f"localhost:{self.port}"):
            raise web.HTTPForbidden()
        from_twitch = request.headers.get("Origin") == TWITCH_ORIGIN
        if request.method == "OPTIONS":
            # CORS preflight from the bookmarklet
            if not from_twitch or request.path != "/api/token":
                raise web.HTTPForbidden()
            response: web.StreamResponse = web.Response(status=204)
            response.headers.update({
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "Content-Type, X-Bridge-Key",
                "Access-Control-Max-Age": "600",
                # Chrome's Private Network Access preflight
                "Access-Control-Allow-Private-Network": "true",
            })
        else:
            response = await handler(request)
        if from_twitch:
            response.headers["Access-Control-Allow-Origin"] = TWITCH_ORIGIN
            response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def _authorized(self, request: web.Request) -> bool:
        """Token deliveries must come either from the bookmarklet, or the popup fallback."""
        origin = request.headers.get("Origin")
        if origin == TWITCH_ORIGIN:
            return secrets.compare_digest(request.headers.get("X-Bridge-Key", ""), self._key)
        elif origin in (None, self.origin):
            return secrets.compare_digest(request.headers.get("X-Bridge-Nonce", ""), self._nonce)
        return False

    def _page(self, template: str, **substitutions: str) -> web.Response:
        html = template.replace("__STYLE__", PAGE_STYLE)
        for key, value in substitutions.items():
            html = html.replace(f"__{key}__", value)
        return web.Response(text=html, content_type="text/html")

    async def _index(self, request: web.Request) -> web.Response:
        bookmarklet = "javascript:" + quote(
            build_bookmarklet(self.port, self._key), safe="(){}[];,:=!&|'+*<>?"
        )
        return self._page(INDEX_HTML, BOOKMARKLET=escape(bookmarklet, quote=True))

    async def _popup(self, request: web.Request) -> web.Response:
        return self._page(POPUP_HTML, NONCE=self._nonce, TWITCH_ORIGIN=TWITCH_ORIGIN)

    async def _state(self, request: web.Request) -> web.Response:
        creds = self.credentials
        state: dict[str, Any] = {
            "connected": self.integrity_valid(),
            "error": self._last_error,
            "expires_local": (
                creds.integrity_expires.astimezone().strftime("%H:%M") if creds else None
            ),
        }
        return web.json_response(state)

    async def _token(self, request: web.Request) -> web.Response:
        if not self._authorized(request) or request.content_type != "application/json":
            raise web.HTTPForbidden()
        try:
            data = await request.json()
            expiration = int(data["expiration"])
            creds = BridgeCredentials(
                auth_token=str(data["auth_token"]),
                device_id=str(data["device_id"]) if data.get("device_id") else None,
                user_agent=str(data["user_agent"]),
                client_version=(
                    str(data["client_version"]) if data.get("client_version") else None
                ),
                integrity_token=str(data["integrity_token"]),
                # expiration is sent in milliseconds
                integrity_expires=datetime.fromtimestamp(expiration / 1000, timezone.utc),
                received_at=datetime.now(timezone.utc),
            )
        except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
            return web.json_response({"error": "malformed token payload"}, status=400)
        try:
            await self._twitch.accept_bridge_credentials(creds)
        except BridgeRejected as exc:
            self._last_error = str(exc)
            return web.json_response({"error": str(exc)}, status=409)
        self.credentials = creds
        self._last_error = None
        self._prompted = False
        self._delivered.set()
        remaining = creds.integrity_expires - creds.received_at
        via = "bookmarklet" if request.headers.get("Origin") == TWITCH_ORIGIN else "popup"
        logger.info(
            f"Received an integrity token from the browser ({via}), "
            f"valid for {remaining.total_seconds() / 60:.0f} minutes"
        )
        return web.json_response({"ok": True})
