"""Historia zakupów allegro: lista i agregat kupionych ofert."""

from __future__ import annotations

from allegro import orders


def test_list_orders_descending(allegro_logged_page):
    result = orders.list_orders(allegro_logged_page, limit=10)
    assert result, "konto ma historię zakupów"
    dates = [o["date"] for o in result if o["date"]]
    assert dates == sorted(dates, reverse=True)
    order = result[0]
    assert order["seller"]
    assert order["items"]
    item = order["items"][0]
    assert item["offerId"] and item["title"]
    assert item["unitPrice"] is None or item["unitPrice"] > 0


def test_purchased_products_aggregate(allegro_logged_page):
    aggregated = orders.purchased_products(allegro_logged_page, max_orders=20)
    assert aggregated
    entry = aggregated[0]
    assert entry["offerId"] and entry["title"]
    assert entry["timesBought"] >= 1
    assert entry["totalQuantity"] >= 1
    assert entry["lastOrderDate"]
    # agregat zawiera pozycje z listy zamówień
    listed_ids = {
        i["offerId"] for o in orders.list_orders(allegro_logged_page, limit=5) for i in o["items"]
    }
    aggregated_ids = {e["offerId"] for e in aggregated}
    assert listed_ids & aggregated_ids
