"""Wspólny klient HTTP dla www.rossmann.pl."""

from __future__ import annotations

import time

import httpx

BASE_URL = "https://www.rossmann.pl"

# Strona odpowiada normalnie na przeglądarkowy User-Agent; goły httpx/curl
# potrafi trafić na challenge Cloudflare.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class RossmannError(Exception):
    """Błąd interfejsu rossmann.pl."""


class ParseError(RossmannError):
    """Struktura strony/odpowiedzi inna niż oczekiwana (zmiana frontu?)."""


class _RetryingClient(httpx.Client):
    """GET-y potrafią dostać przejściowe 502 z gatewaya — jedna ponowna próba wystarcza."""

    def request(self, method: str, url, **kwargs) -> httpx.Response:
        resp = super().request(method, url, **kwargs)
        if resp.status_code in (502, 503, 504) and method.upper() == "GET":
            time.sleep(1)
            resp = super().request(method, url, **kwargs)
        return resp


def make_client(token: str | None = None) -> httpx.Client:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "pl-PL,pl;q=0.9",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _RetryingClient(
        base_url=BASE_URL,
        headers=headers,
        timeout=30,
        follow_redirects=True,
    )
