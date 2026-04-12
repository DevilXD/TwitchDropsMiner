from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LoginData:
    username: str
    password: str
    token: str
