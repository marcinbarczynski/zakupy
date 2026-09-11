"""Sesja przeglądarki dla allegro.pl.

Allegro siedzi za DataDome: goły HTTP (httpx/curl) dostaje 403 albo captchę,
więc CLI steruje prawdziwym chromium przez Playwright. Dane listingu są
osadzone w HTML (script application/json z __listing_StoreState) — ustalone
inspekcją strony 2026-07-12.

Sesja (cookies DataDome + zalogowanie) żyje w trwałym profilu
~/.cache/allegro-cli/profile. Profil znosi tylko jedną instancję przeglądarki
naraz, dlatego wywołania CLI serializuje file-lock (czekają, nie wywalają się).

Uwaga: DataDome wykrywa KAŻDY wariant headless (headless shell, chrome
--headless=new, headed pod Xvfb) i po takiej próbie flaguje też profil —
sprawdzone empirycznie 2026-07-12. Dlatego CLI zawsze odpala prawdziwego
Chrome'a w trybie headed na realnym pulpicie, tylko z oknem odsuniętym poza
ekran; wymaga aktywnej sesji graficznej.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # playwright importujemy leniwie — start CLI bez niego ma czytelny błąd
    from playwright.sync_api import Page

BASE_URL = "https://allegro.pl"

_CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "allegro-cli"
PROFILE_DIR = _CACHE_DIR / "profile"
_COOKIES_FILE = _CACHE_DIR / "cookies.json"  # sesyjne cookies giną przy zamknięciu Chrome'a, więc je przenosimy sami
_LOCK_FILE = _CACHE_DIR / "browser.lock"
_LOCK_TIMEOUT = 180.0

_NAV_TIMEOUT_MS = 45_000


class AllegroError(Exception):
    """Błąd interfejsu allegro.pl."""


class ParseError(AllegroError):
    """Struktura strony inna niż oczekiwana (zmiana frontu?)."""


class BlockedError(AllegroError):
    """DataDome zablokował sesję (captcha)."""


@contextmanager
def _profile_lock() -> Iterator[None]:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_LOCK_FILE, "w") as fh:
        deadline = time.monotonic() + _LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise AllegroError(
                        "inny proces allegro-cli trzyma przeglądarkę od ponad "
                        f"{int(_LOCK_TIMEOUT)} s — wywołania muszą być sekwencyjne"
                    ) from None
                time.sleep(0.5)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@contextmanager
def open_page(headful: bool = False) -> Iterator["Page"]:
    """Jedna karta w trwałym profilu; zamyka przeglądarkę przy wyjściu.

    Zawsze headed (patrz docstring modułu); headful=True tylko pokazuje okno
    na ekranie zamiast parkować je poza nim (logowanie z 2FA, unblock).
    """
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as e:
        raise AllegroError("brak pakietu playwright — uruchom: uv sync") from e

    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise AllegroError(
            "brak sesji graficznej (DISPLAY) — allegro-cli wymaga pulpitu, "
            "bo headless jest wykrywany przez DataDome"
        )

    args = ["--disable-blink-features=AutomationControlled"]
    if not headful:
        args.append("--window-position=3000,3000")  # okno poza ekranem zamiast headless

    with _profile_lock():
        with sync_playwright() as pw:
            try:
                ctx = pw.chromium.launch_persistent_context(
                    str(PROFILE_DIR),
                    channel="chrome",  # systemowy Chrome przechodzi DataDome, buildy Playwrighta nie zawsze
                    headless=False,
                    locale="pl-PL",
                    timezone_id="Europe/Warsaw",
                    viewport={"width": 1280, "height": 900},
                    args=args,
                )
            except PlaywrightError as e:
                if "Chromium distribution 'chrome' is not found" in str(e):
                    raise AllegroError(
                        "brak systemowego Google Chrome — zainstaluj go albo: "
                        "uv run playwright install chrome"
                    ) from e
                raise AllegroError(f"nie udało się uruchomić przeglądarki: {e}") from e
            try:
                _restore_cookies(ctx)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.set_default_timeout(_NAV_TIMEOUT_MS)
                page.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
                yield page
            finally:
                _save_cookies(ctx)
                ctx.close()


def _restore_cookies(ctx: Any) -> None:
    if not _COOKIES_FILE.exists():
        return
    try:
        ctx.add_cookies(json.loads(_COOKIES_FILE.read_text()))
    except Exception:
        pass  # uszkodzony plik cookies nie może blokować CLI; nadpisze się przy wyjściu


def _save_cookies(ctx: Any) -> None:
    try:
        cookies = ctx.cookies()
        _COOKIES_FILE.write_text(json.dumps(cookies))
        _COOKIES_FILE.chmod(0o600)
    except Exception:
        pass


def _looks_blocked(page: "Page") -> bool:
    """Strona-przekładka DataDome: malutki dokument z captchą z captcha-delivery.com."""
    try:
        html = page.content()
    except Exception:
        return False
    return "captcha-delivery.com" in html and len(html) < 50_000


def _maybe_accept_consent(page: "Page") -> None:
    """Zamknij dialog zgód (pierwsze uruchomienie profilu); brak dialogu to nie błąd."""
    try:
        button = page.locator('button[data-role="accept-consent"]')
        if not button.count():
            button = page.get_by_role("button", name="Zgadzam się", exact=True)
        if button.count():
            button.first.click(timeout=3_000)
            page.wait_for_timeout(300)
    except Exception:
        pass


def goto(page: "Page", url: str, *, warm_up: bool = True) -> None:
    """Nawigacja z obsługą zgód i przekładki DataDome.

    Świeży profil bywa blokowany na /listing, ale strona główna przechodzi
    i ustawia cookie DataDome — stąd rozgrzewka i jedna ponowna próba.
    """
    page.goto(url, wait_until="domcontentloaded")
    _maybe_accept_consent(page)
    if not _looks_blocked(page):
        return
    if warm_up:
        page.goto(BASE_URL + "/", wait_until="domcontentloaded")
        _maybe_accept_consent(page)
        page.wait_for_timeout(1_000)
        page.goto(url, wait_until="domcontentloaded")
        if not _looks_blocked(page):
            return
    raise BlockedError(
        "DataDome pokazał captchę — uruchom `allegro unblock`, rozwiąż ją w oknie i spróbuj ponownie"
    )


def listing_state(page: "Page") -> dict[str, Any]:
    """Wyciągnij __listing_StoreState z osadzonego JSON-a strony listingu."""
    payload = page.evaluate(
        """() => {
            for (const s of document.querySelectorAll('script[type="application/json"]')) {
                const t = s.textContent || '';
                if (t.includes('__listing_StoreState')) return t;
            }
            return null;
        }"""
    )
    if payload is None:
        raise ParseError("brak __listing_StoreState na stronie (to nie listing albo zmiana frontu)")
    try:
        return json.loads(payload)["__listing_StoreState"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ParseError(f"niepoprawny __listing_StoreState: {e}") from e
