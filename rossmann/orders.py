"""Historia zamówień konta rossmann.pl.

Endpointy ustalone przez inspekcję frontu (2026-07-12):
- GET /orders/order/grouped-history?rowsCount=10&startIndex=N — lista zamówień
  (podgląd maks. 4 produktów w productsInfosHistory + licznik otherItems)
- GET /orders/order/online/{orderId} — pełne szczegóły zamówienia online,
  produkty w productsSummary.products (id == id katalogowe)
Oba z nagłówkiem Authorization: Bearer <token>.

Agregat obejmuje wyłącznie zamówienia online (orderType 1) — zamówienia
offline (paragony ze sklepu) mają osobny endpoint i inny format.
"""

from __future__ import annotations

from typing import Any

import httpx

from .http import RossmannError

_PAGE_SIZE = 10
_ORDER_TYPE_ONLINE = 1


class OrdersError(RossmannError):
    pass


def _check(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise OrdersError("Brak autoryzacji (401) — zaloguj się: rossmann login")
    resp.raise_for_status()


def list_orders(client: httpx.Client, limit: int = 50) -> list[dict[str, Any]]:
    """Lista zamówień od najnowszego (orderId, orderDate, price, status, podgląd produktów)."""
    orders: list[dict[str, Any]] = []
    start = 0
    while len(orders) < limit:
        resp = client.get(
            "/orders/order/grouped-history",
            params={"rowsCount": _PAGE_SIZE, "startIndex": start},
        )
        _check(resp)
        batch = resp.json().get("orders") or []
        orders.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return orders[:limit]


def order_details(client: httpx.Client, order_id: int) -> dict[str, Any]:
    """Pełne szczegóły zamówienia online: productsSummary, paymentSummary, orderDetails itd."""
    resp = client.get(f"/orders/order/online/{order_id}")
    if resp.status_code == 404:
        raise OrdersError(f"Zamówienie {order_id} nie znalezione (albo nie jest online)")
    _check(resp)
    return resp.json()


def purchased_products(client: httpx.Client, max_orders: int = 50) -> list[dict[str, Any]]:
    """Agregat kupionych produktów z zamówień online, od ostatnio kupionych.

    Per produkt: id, brand, name, caption, unit, picture, url,
    timesBought (w ilu zamówieniach), totalQuantity, lastOrderDate, lastUnitPrice.
    """
    aggregated: dict[int, dict[str, Any]] = {}
    online = [o for o in list_orders(client, limit=max_orders)
              if o.get("orderType") == _ORDER_TYPE_ONLINE]
    # od najstarszego: kolejne wystąpienia nadpisują lastOrderDate/lastUnitPrice najnowszymi
    for order in sorted(online, key=lambda o: o.get("orderDate") or ""):
        details = order_details(client, order["orderId"])
        for p in (details.get("productsSummary") or {}).get("products") or []:
            entry = aggregated.setdefault(p["id"], {
                "id": p["id"],
                "brand": p.get("brand"),
                "name": (p.get("name") or "").strip(),
                "caption": p.get("caption"),
                "unit": p.get("unit"),
                "picture": p.get("picture"),
                "url": p.get("navigateUrl"),
                "timesBought": 0,
                "totalQuantity": 0,
            })
            entry["timesBought"] += 1
            entry["totalQuantity"] += p.get("quantity") or 0
            entry["lastOrderDate"] = order.get("orderDate")
            entry["lastUnitPrice"] = p.get("unitPrice")
    return sorted(aggregated.values(), key=lambda e: e.get("lastOrderDate") or "", reverse=True)
