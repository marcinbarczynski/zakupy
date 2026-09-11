"""Logowanie do allegro.pl danymi z pliku .allegro.

Nie ma tu tokenów — sesją zarządza trwały profil przeglądarki (browser.py).
Pierwsze logowanie może wymagać captchy albo potwierdzenia (2FA) — wtedy
trzeba je dokończyć ręcznie w oknie: `allegro login --headful`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .browser import BASE_URL, AllegroError, goto

if TYPE_CHECKING:
    from playwright.sync_api import Page

DEFAULT_CREDENTIALS_FILE = Path(__file__).parent.parent / ".allegro"

_LOGIN_URL = BASE_URL + "/logowanie"
# strona wymagająca zalogowania: bez sesji przekierowuje na /logowanie
_PURCHASES_URL = BASE_URL + "/moje-allegro/zakupy/kupione"


class AuthError(AllegroError):
    """Problem z logowaniem/kontem."""


@dataclass
class Credentials:
    email: str
    password: str

    @classmethod
    def load(cls, path: Path | None = None) -> "Credentials":
        path = path or DEFAULT_CREDENTIALS_FILE
        if not path.exists():
            raise AuthError(f"brak pliku z danymi logowania: {path}")
        values: dict[str, str] = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
        try:
            return cls(email=values["EMAIL"], password=values["PASSWORD"])
        except KeyError as e:
            raise AuthError(f"w {path} brakuje pola {e.args[0]}") from e


def _on_login_page(page: "Page") -> bool:
    return "/logowanie" in page.url or "/auth/" in page.url or "/login" in page.url


def is_logged_in(page: "Page") -> bool:
    goto(page, _PURCHASES_URL)
    return not _on_login_page(page)


def whoami(page: "Page") -> dict[str, Any]:
    """Tożsamość zalogowanego konta (login/imię z nagłówka lub skryptów strony)."""
    if not is_logged_in(page):
        raise AuthError("niezalogowany — uruchom: allegro login")
    info = page.evaluate(
        r"""() => {
            const out = {};
            for (const s of document.querySelectorAll('script')) {
                const t = s.textContent || '';
                // marketplaceLogin to login zalogowanego konta; "login" bez prefiksu to sprzedawcy
                const m = t.match(/"marketplaceLogin"\s*:\s*"([^"]{1,60})"/);
                if (m && !out.login) out.login = m[1];
                const e = t.match(/"(?:userEmail|email)"\s*:\s*"([^"@]+@[^"]+)"/);
                if (e && !out.email) out.email = e[1];
            }
            const w = document.body.innerText.match(/([\p{L}]+)\s*\njesteś/u);
            if (w) out.firstName = w[1];
            return out;
        }"""
    )
    return {"loggedIn": True, **{k: v for k, v in (info or {}).items() if v}}


def _dismiss_post_login_nags(page: "Page") -> None:
    """Po zalogowaniu allegro wciska przejściówki ("uzupełnij telefon") — sesja już działa."""
    if "aktualizacja-danych" not in page.url:
        return
    try:
        button = page.get_by_role("button", name=re.compile("później|pomiń|nie teraz", re.I))
        if button.count():
            button.first.click(timeout=3_000)
            page.wait_for_timeout(1_000)
    except Exception:
        pass


def login(page: "Page", credentials: Credentials | None = None, headful: bool = False) -> None:
    """Wypełnij formularz logowania; przy captcha/2FA wymaga trybu headful.

    Selektory pól ustalone z live formularza /log-in (2026-07-12).
    """
    credentials = credentials or Credentials.load()
    if is_logged_in(page):
        return
    goto(page, _LOGIN_URL)
    form = 'form:has(input[name="password"])'
    page.fill(f'{form} input[name="login"]', credentials.email)
    page.fill(f'{form} input[name="password"]', credentials.password)
    page.click(f'{form} button[type="submit"]')
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3_000)
    _dismiss_post_login_nags(page)
    if _on_login_page(page) and "aktualizacja-danych" not in page.url:
        if headful:
            # człowiek dokańcza w oknie (captcha / 2FA); czekamy aż zniknie strona logowania
            page.wait_for_url(
                lambda url: not any(part in url for part in ("/logowanie", "/auth/", "/login")),
                timeout=300_000,
            )
        else:
            hint = page.evaluate("() => document.body.innerText.slice(0, 400)")
            raise AuthError(
                "logowanie nie przeszło automatycznie (captcha/2FA?) — uruchom: "
                f"allegro login --headful\nstrona mówi: {' '.join(hint.split())[:200]}"
            )
    if not is_logged_in(page):
        raise AuthError("logowanie nieudane — sprawdź dane w .allegro")
