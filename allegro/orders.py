"""Historia zakupów: strona /moje-allegro/zakupy/kupione (wymaga zalogowania).

Dane siedzą w osadzonym JSON-ie z kluczem "myorders" (orderGroups -> myorders
-> offers); paginacja przez parametry limit/offset. Ustalone 2026-07-12.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from .auth import AuthError
from .browser import BASE_URL, ParseError, goto

if TYPE_CHECKING:
    from playwright.sync_api import Page

_PURCHASES_URL = BASE_URL + "/moje-allegro/zakupy/kupione"
_PAGE_SIZE = 15  # tyle zwraca strona niezależnie od parametru limit


class OrdersError(AuthError):
    """Problem z historią zamówień."""


def _orders_state(page: "Page", offset: int = 0) -> dict[str, Any]:
    url = _PURCHASES_URL + (f"?limit={_PAGE_SIZE}&offset={offset}" if offset else "")
    goto(page, url)
    if "/logowanie" in page.url:
        raise AuthError("niezalogowany — uruchom: allegro login")
    payload = page.evaluate(
        """() => {
            for (const s of document.querySelectorAll('script[type="application/json"]')) {
                const t = s.textContent || '';
                if (t.includes('"myorders"')) return t;
            }
            return null;
        }"""
    )
    if payload is None:
        raise ParseError("brak danych zamówień na stronie kupione (zmiana frontu?)")
    try:
        return json.loads(payload)["myorders"]
    except (json.JSONDecodeError, KeyError) as e:
        raise ParseError(f"niepoprawne dane zamówień: {e}") from e


def _clean_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)  # friendlyUrl ma jednorazowy parametr snapshot
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _order_entry(order: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    offers = order.get("offers") or []
    return {
        "orderId": order.get("id"),
        "date": min((o.get("orderDate") for o in offers if o.get("orderDate")), default=None),
        "seller": (order.get("seller") or {}).get("login"),
        "totalPrice": _price(group.get("totalCost")),
        "deliveryCost": _price(((order.get("delivery") or {}).get("cost"))),
        "items": [
            {
                "offerId": o.get("id"),
                "title": o.get("title"),
                "unitPrice": _price(o.get("unitPrice")),
                "quantity": o.get("quantity"),
                "productId": o.get("productId"),
                "url": _clean_url(o.get("friendlyUrl")),
                "picture": o.get("imageUrl"),
            }
            for o in offers
        ],
    }


def _price(d: Any) -> float | None:
    if isinstance(d, dict) and d.get("amount") is not None:
        try:
            return float(d["amount"])
        except (TypeError, ValueError):
            return None
    return None


def list_orders(page: "Page", limit: int = 20) -> list[dict[str, Any]]:
    """Zamówienia od najnowszego; jedno zamówienie = jeden sprzedawca."""
    result: list[dict[str, Any]] = []
    offset = 0
    total = None
    while len(result) < limit and (total is None or offset < total):
        state = _orders_state(page, offset=offset)
        total = state.get("total")
        groups = state.get("orderGroups") or []
        if not groups:
            break
        for group in groups:
            for order in group.get("myorders") or []:
                result.append(_order_entry(order, group))
        offset += len(groups)
    return result[:limit]


def purchased_products(page: "Page", max_orders: int = 50) -> list[dict[str, Any]]:
    """Agregat kupionych ofert: ile razy, ile sztuk, kiedy ostatnio, po ile."""
    aggregated: dict[str, dict[str, Any]] = {}
    for order in list_orders(page, limit=max_orders):
        for item in order["items"]:
            offer_id = item.get("offerId")
            if not offer_id:
                continue
            entry = aggregated.setdefault(
                offer_id,
                {
                    "offerId": offer_id,
                    "title": item.get("title"),
                    "productId": item.get("productId"),
                    "url": item.get("url"),
                    "picture": item.get("picture"),
                    "seller": order.get("seller"),
                    "timesBought": 0,
                    "totalQuantity": 0,
                    "lastOrderDate": None,
                    "lastUnitPrice": None,
                },
            )
            entry["timesBought"] += 1
            entry["totalQuantity"] += item.get("quantity") or 0
            date = order.get("date")
            if date and (entry["lastOrderDate"] is None or date > entry["lastOrderDate"]):
                entry["lastOrderDate"] = date
                entry["lastUnitPrice"] = item.get("unitPrice")
    return sorted(aggregated.values(), key=lambda e: e["lastOrderDate"] or "", reverse=True)
