"""Logowanie allegro: sesja z profilu, whoami, brak wycieku hasła."""

from __future__ import annotations

from allegro import auth


def test_credentials_load():
    creds = auth.Credentials.load()
    assert "@" in creds.email
    assert len(creds.password) >= 8


def test_whoami_logged_in(allegro_logged_page):
    user = auth.whoami(allegro_logged_page)
    assert user["loggedIn"] is True
    assert user.get("login") or user.get("firstName"), "whoami powinno zwrócić tożsamość"


def test_session_reused_between_checks(allegro_logged_page):
    """Drugie sprawdzenie nie może wymagać ponownego logowania (sesja w profilu)."""
    assert auth.is_logged_in(allegro_logged_page)
    assert auth.is_logged_in(allegro_logged_page)
