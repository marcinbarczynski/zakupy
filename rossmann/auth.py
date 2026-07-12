"""Logowanie i cache tokenu.

Przechwycone z ruchu przeglądarki (2026-07-11):
- POST /auth/token            {"userName", "password"}  -> {"data": {"token", "expiry"}}
- POST /auth/tokens/refreshment {"token": <stary token>} -> {"data": {"token", "expiry"}}
- GET  /usr/api/user?timestamp=...  z nagłówkiem Authorization: Bearer <token>
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .http import RossmannError, make_client

DEFAULT_CREDENTIALS_FILE = Path(__file__).resolve().parent.parent / ".rossmann"
TOKEN_CACHE = Path(
    os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
) / "rossmann-cli" / "token.json"


class AuthError(RossmannError):
    pass


@dataclass
class Credentials:
    email: str
    password: str

    @classmethod
    def load(cls, path: Path | None = None) -> "Credentials":
        path = path or DEFAULT_CREDENTIALS_FILE
        if not path.exists():
            raise AuthError(f"Brak pliku z danymi logowania: {path}")
        values: dict[str, str] = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
        try:
            return cls(email=values["EMAIL"], password=values["PASSWORD"])
        except KeyError as e:
            raise AuthError(f"W {path} brakuje pola {e}") from None


def _save_token(token: str, expiry: str | None) -> None:
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(json.dumps({"token": token, "expiry": expiry, "saved_at": time.time()}))
    TOKEN_CACHE.chmod(0o600)


def _read_cached_token() -> dict | None:
    try:
        return json.loads(TOKEN_CACHE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _token_expired(cached: dict) -> bool:
    expiry = cached.get("expiry")
    if not expiry:
        return True
    try:
        # expiry to uniksowy timestamp (sekundy), np. "1783805396"; margines 60 s
        return float(expiry) - 60 <= time.time()
    except (TypeError, ValueError):
        return True


def _extract_token(resp: httpx.Response) -> tuple[str, str | None]:
    if resp.status_code in (400, 401, 403):
        raise AuthError(f"Logowanie odrzucone (HTTP {resp.status_code}): {resp.text[:200]}")
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    token = data.get("token")
    if not token:
        raise AuthError(f"Odpowiedź bez tokenu: {resp.text[:200]}")
    return token, data.get("expiry")


def login(credentials: Credentials | None = None) -> str:
    """Zaloguj się i zwróć świeży token (zapisany też w cache)."""
    creds = credentials or Credentials.load()
    with make_client() as client:
        resp = client.post(
            "/auth/token", json={"userName": creds.email, "password": creds.password}
        )
    token, expiry = _extract_token(resp)
    _save_token(token, expiry)
    return token


def refresh(token: str) -> str | None:
    """Odśwież token; None gdy odświeżenie odrzucone."""
    with make_client() as client:
        resp = client.post("/auth/tokens/refreshment", json={"token": token})
    try:
        new_token, expiry = _extract_token(resp)
    except (AuthError, httpx.HTTPStatusError):
        return None
    _save_token(new_token, expiry)
    return new_token


def get_token(force_login: bool = False) -> str:
    """Token z cache; przeterminowany odśwież, w ostateczności zaloguj od nowa."""
    if not force_login:
        cached = _read_cached_token()
        if cached and cached.get("token"):
            if not _token_expired(cached):
                return cached["token"]
            refreshed = refresh(cached["token"])
            if refreshed:
                return refreshed
    return login()


def whoami(token: str) -> dict:
    """Profil zalogowanego użytkownika."""
    with make_client(token=token) as client:
        resp = client.get("/usr/api/user", params={"timestamp": int(time.time() * 1000)})
        if resp.status_code == 401:
            raise AuthError("Token nieważny (401)")
        resp.raise_for_status()
        body = resp.json()
    return body.get("data") or body
