"""Scenariusz 4: historia zamówień i agregat kupionych produktów (tylko odczyt)."""

from __future__ import annotations

from rossmann import orders

_ORDER_TYPE_ONLINE = 1


def test_orders_history_and_aggregate(authed_client):
    listed = orders.list_orders(authed_client, limit=20)
    assert listed, "konto ma zamówienia — lista nie powinna być pusta"

    online = [o for o in listed if o.get("orderType") == _ORDER_TYPE_ONLINE]
    assert online, "konto ma zamówienia online"
    # offline'y (paragony) bywają wplecione poza porządkiem — sortowanie
    # gwarantowane tylko w obrębie zamówień online
    dates = [o.get("orderDate") or "" for o in online]
    assert dates == sorted(dates, reverse=True), "zamówienia online od najnowszego"
    details = orders.order_details(authed_client, online[0]["orderId"])
    products = (details.get("productsSummary") or {}).get("products") or []
    assert products
    for p in products:
        assert isinstance(p["id"], int)
        assert p["quantity"] >= 1
        assert p["unitPrice"] > 0

    aggregated = orders.purchased_products(authed_client, max_orders=5)
    by_id = {e["id"]: e for e in aggregated}
    assert products[0]["id"] in by_id, "produkt ze szczegółów musi być w agregacie"
    entry = by_id[products[0]["id"]]
    assert entry["timesBought"] >= 1
    assert entry["totalQuantity"] >= products[0]["quantity"]
    assert entry["lastOrderDate"] >= online[-1].get("orderDate", "")
