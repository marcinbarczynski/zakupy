"""Scenariusz 3: pełny roundtrip koszyka na koncie.

Test dodaje produkt, weryfikuje zawartość i po sobie sprząta (finally).
Pozycji obecnych w koszyku przed testem nie dotyka.
"""

from __future__ import annotations

import pytest

from rossmann import basket, catalog


@pytest.fixture()
def test_product(authed_client):
    """Tani, dostępny produkt, którego nie ma jeszcze w koszyku."""
    in_basket = {i["id"] for i in basket.show(authed_client).get("cartItems") or []}
    candidates = catalog.cheapest(authed_client, query="szampon", limit=10)
    product = next(p for p in candidates if p.id not in in_basket)
    return catalog.product_details(authed_client, product.id)


def test_basket_roundtrip(authed_client, test_product):
    before = basket.show(authed_client)
    before_ids = {i["id"] for i in before.get("cartItems") or []}
    try:
        message = basket.add(authed_client, test_product.raw, quantity=2)
        assert "dodane" in message.lower() or message == "OK"

        data = basket.show(authed_client)
        items = {i["id"]: i for i in data.get("cartItems") or []}
        assert test_product.id in items
        assert items[test_product.id]["quantity"] == 2
        assert data["totalProductQuantity"] >= 2
        assert data["totalPrice"] > 0
    finally:
        current = {i["id"] for i in basket.show(authed_client).get("cartItems") or []}
        if test_product.id in current and test_product.id not in before_ids:
            basket.remove(authed_client, test_product.id)

    after_ids = {i["id"] for i in basket.show(authed_client).get("cartItems") or []}
    assert after_ids == before_ids, "koszyk powinien wrócić do stanu sprzed testu"


def test_remove_nonexistent_item_raises(authed_client):
    in_basket = {i["id"] for i in basket.show(authed_client).get("cartItems") or []}
    assert 999999999 not in in_basket
    with pytest.raises(basket.BasketError):
        basket.remove(authed_client, 999999999)
