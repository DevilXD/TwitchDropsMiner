import json
import os
import sqlite3
import time
from secrets import token_urlsafe

import jwt
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from nicegui import app, ui
from pwdlib import PasswordHash
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from constants import CONFIG_PATH


class AuthManager:
    AUTH_ENABLED = os.environ.get("WEBUI_AUTH", "0") == "1"
    _COOKIE = "tdm_auth"
    _COOKIE_MAX_AGE = 86400 * 30
    _UNPROTECTED = ("/login", "/auth", "/_nicegui", "/icons", "/favicon.ico")
    _DB_PATH = CONFIG_PATH / "webui_auth.db"

    def __init__(self):
        if not AuthManager.AUTH_ENABLED:
            return
        self._ph = PasswordHash.recommended()
        self._limiter = Limiter(key_func=get_remote_address)
        self._db = self._init_db()
        self._secret = self._init_jwt_secret()
        self._setup()

    def _init_db(self):
        CONFIG_PATH.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(AuthManager._DB_PATH), check_same_thread=False)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, hash TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY, value TEXT)"
        )
        return conn

    def _init_jwt_secret(self):
        row = self._db.execute(
            "SELECT value FROM config WHERE key='jwt_secret'"
        ).fetchone()
        if row:
            return row[0]
        secret = token_urlsafe(48)
        self._db.execute("INSERT INTO config VALUES('jwt_secret', ?)", (secret,))
        self._db.commit()
        return secret

    def _get_pw_hash(self, username):
        row = self._db.execute(
            "SELECT hash FROM users WHERE username=?", (username,)
        ).fetchone()
        return row[0] if row else None

    def _db_has_user(self):
        return self._db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def _add_user(self, username, hashed):
        self._db.execute("INSERT OR IGNORE INTO users VALUES(?,?)", (username, hashed))
        self._db.commit()

    def _make_jwt(self, subject):
        now = int(time.time())
        return jwt.encode(
            {
                "sub": subject,
                "aud": "tdm",
                "iat": now,
                "exp": now + self._COOKIE_MAX_AGE,
            },
            self._secret,
            algorithm="HS256",
        )

    def _valid_jwt(self, token):
        try:
            jwt.decode(token, self._secret, algorithms=["HS256"], audience=["tdm"])
            return True
        except Exception:
            return False

    @staticmethod
    def _auth_js(username, password):
        body = json.dumps({"username": username, "password": password})
        return f"""
        fetch('/auth/login', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: '{body}'
        }}).then(r => r.ok
            ? location.href = '/'
            : r.json().then(e => Quasar.Notify.create({{type: 'negative', message: e.detail}}))
        );
        """

    @staticmethod
    def logout_js():
        return "fetch('/auth/logout',{method:'POST'}).then(()=>location.href='/login')"

    def _setup(self):
        app.state.limiter = self._limiter
        app.add_exception_handler(
            RateLimitExceeded,
            lambda req, exc: JSONResponse(
                {"detail": "Rate limit exceeded"}, status_code=429
            ),
        )

        @app.middleware("http")
        async def auth_middleware(request, call_next):
            path = request.url.path
            if any(
                path == p or path.startswith(p + "/") for p in self._UNPROTECTED
            ) or self._valid_jwt(request.cookies.get(self._COOKIE, "")):
                return await call_next(request)
            return (
                RedirectResponse("/login", 303)
                if request.method in ("GET", "HEAD")
                else JSONResponse({"detail": "Unauthorized"}, 401)
            )

        @app.post("/auth/login")
        @self._limiter.limit("5/minute")
        async def login_endpoint(request: Request):
            body = await request.json()
            username = body.get("username", "").strip()
            password = body.get("password", "")
            if not username or not password:
                raise HTTPException(400, detail="Username and password required")
            if not self._db_has_user():
                self._add_user(username, self._ph.hash(password))
            else:
                stored_hash = self._get_pw_hash(username)
                if not stored_hash:
                    raise HTTPException(400, detail="Invalid credentials")
                try:
                    valid = self._ph.verify(password, stored_hash)
                except Exception:
                    valid = False
                if not valid:
                    raise HTTPException(400, detail="Invalid credentials")
            response = Response(status_code=204)
            response.set_cookie(
                self._COOKIE,
                self._make_jwt(username),
                max_age=self._COOKIE_MAX_AGE,
                path="/",
                httponly=True,
                samesite="lax",
            )
            return response

        @app.post("/auth/logout")
        async def logout_endpoint():
            response = Response(status_code=204)
            response.delete_cookie(self._COOKIE, path="/")
            return response

        @ui.page("/login")
        def login_page():
            first_run = not self._db_has_user()
            ui.dark_mode(True)
            with ui.card().classes("absolute-center w-96"):
                ui.label("Twitch Drops Miner").classes(
                    "text-h5 text-center w-full mb-2"
                )
                if first_run:
                    ui.label("Create an admin account").classes(
                        "text-center w-full text-grey mb-2"
                    )
                username_input = ui.input("Username").classes("w-full")
                password_input = ui.input(
                    "Password", password=True, password_toggle_button=True
                ).classes("w-full")
                confirm_input = (
                    ui.input(
                        "Confirm password", password=True, password_toggle_button=True
                    ).classes("w-full")
                    if first_run
                    else None
                )

                async def on_submit():
                    username, password = (
                        username_input.value.strip(),
                        password_input.value,
                    )
                    if not username:
                        return ui.notify("Username Required", type="negative")
                    if not password:
                        return ui.notify("Password Required", type="negative")
                    if first_run and password != confirm_input.value:
                        return ui.notify("Password Mismatch", type="negative")
                    ui.run_javascript(AuthManager._auth_js(username, password))

                ui.button(
                    "Register" if first_run else "Sign in", on_click=on_submit
                ).classes("w-full mt-2")
                for inp in (username_input, password_input, confirm_input):
                    if inp:
                        inp.on("keydown.enter", on_submit)
