"""Scenariusz 2: logowanie na żywym API — token, whoami, cache."""

from __future__ import annotations

import time

from rossmann import auth


def test_login_returns_valid_token_and_whoami_matches_credentials():
    creds = auth.Credentials.load()
    token = auth.login(creds)
    assert token and len(token) > 20

    cached = auth._read_cached_token()
    assert cached["token"] == token
    assert float(cached["expiry"]) > time.time(), "token powinien wygasać w przyszłości"

    user = auth.whoami(token)
    assert user["email"].lower() == creds.email.lower()


def test_token_cache_is_reused_without_relogin():
    auth.get_token()  # zapewnij świeży cache
    mtime_before = auth.TOKEN_CACHE.stat().st_mtime
    token = auth.get_token()
    assert token
    assert auth.TOKEN_CACHE.stat().st_mtime == mtime_before, (
        "drugie get_token() nie powinno logować się ponownie"
    )


def test_token_cache_is_private_and_has_no_password():
    auth.get_token()
    creds = auth.Credentials.load()
    mode = auth.TOKEN_CACHE.stat().st_mode & 0o777
    assert mode == 0o600
    content = auth.TOKEN_CACHE.read_text()
    assert creds.password not in content


def test_refresh_returns_new_usable_token():
    token = auth.login()
    refreshed = auth.refresh(token)
    assert refreshed
    user = auth.whoami(refreshed)
    assert user["email"]
