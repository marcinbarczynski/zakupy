"""Koszyk na koncie rossmann.pl.

Przechwycone z ruchu przeglądarki (2026-07-11):
- GET    /shopping/api/v2/Cart/summary/details?shopNumber=&shippingDestination=&deliveryTypeId=&version=
- POST   /basket/api/Basket/items   body: [ {<obiekt produktu>, "quantity": n} ]
- DELETE /basket/api/Basket/items   body: [ {<pozycja koszyka z cartItems>} ]
Wszystkie z nagłówkiem Authorization: Bearer <token>.
"""

from __future__ import annotations

from typing import Any

import httpx

from .http import RossmannError

# Parametry, z którymi frontend woła podsumowanie koszyka (9501 = sklep internetowy).
_CART_PARAMS = {
    "shopNumber": 9501,
    "shippingDestination": 9501,
    "deliveryTypeId": 2,
    "version": "20241118",
}


class BasketError(RossmannError):
    pass


def _check(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise BasketError("Brak autoryzacji (401) — zaloguj się: rossmann login")
    resp.raise_for_status()


def show(client: httpx.Client) -> dict[str, Any]:
    """Zawartość koszyka: cartItems, totalPrice, totalProductQuantity itd."""
    resp = client.get("/shopping/api/v2/Cart/summary/details", params=_CART_PARAMS)
    _check(resp)
    return resp.json().get("data") or {}


def add(client: httpx.Client, product_raw: dict[str, Any], quantity: int = 1) -> str:
    """Dodaj produkt do koszyka. product_raw = pełny obiekt produktu (Product.raw)."""
    if quantity < 1:
        raise BasketError("quantity musi być >= 1")
    item = {**product_raw, "quantity": quantity}
    resp = client.post("/basket/api/Basket/items", json=[item])
    _check(resp)
    body = resp.json() if resp.content else {}
    return body.get("data") or "OK"


def remove(client: httpx.Client, product_id: int) -> None:
    """Usuń pozycję z koszyka (całą, niezależnie od ilości)."""
    items = show(client).get("cartItems") or []
    matches = [i for i in items if i.get("id") == product_id]
    if not matches:
        raise BasketError(f"Produktu {product_id} nie ma w koszyku")
    resp = client.request("DELETE", "/basket/api/Basket/items", json=matches)
    _check(resp)


def clear(client: httpx.Client) -> int:
    """Usuń wszystkie pozycje; zwraca liczbę usuniętych."""
    items = show(client).get("cartItems") or []
    if items:
        resp = client.request("DELETE", "/basket/api/Basket/items", json=items)
        _check(resp)
    return len(items)
