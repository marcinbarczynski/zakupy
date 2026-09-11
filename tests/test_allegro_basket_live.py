"""Rundtrip koszyka allegro: dodaj, zweryfikuj, posprzątaj (finally).

Pozycji obecnych w koszyku przed testem nie dotyka.
"""

from __future__ import annotations

import pytest

from allegro import basket, listing


@pytest.fixture()
def test_offer(allegro_logged_page):
    """Tania, dostępna oferta, której nie ma jeszcze w koszyku."""
    in_basket = {i["offerId"] for i in basket.show(allegro_logged_page)["items"]}
    result = listing.search(allegro_logged_page, "domestos zagęszczony 750", sort="price")
    return next(
        o
        for o in result.offers
        if o.cart_available and o.offer_id not in in_basket and o.price and o.price < 30
    )


def test_basket_roundtrip(allegro_logged_page, test_offer):
    page = allegro_logged_page
    before_ids = {i["offerId"] for i in basket.show(page)["items"]}
    try:
        title = basket.add(page, test_offer.offer_id, quantity=2)
        assert title

        data = basket.show(page)
        items = {i["offerId"]: i for i in data["items"]}
        assert test_offer.offer_id in items
        assert items[test_offer.offer_id]["quantity"] == 2
        assert data["totalPrice"] > 0
    finally:
        current = {i["offerId"] for i in basket.show(page)["items"]}
        if test_offer.offer_id in current and test_offer.offer_id not in before_ids:
            basket.remove(page, test_offer.offer_id)

    after_ids = {i["offerId"] for i in basket.show(page)["items"]}
    assert after_ids == before_ids, "koszyk powinien wrócić do stanu sprzed testu"


def test_remove_nonexistent_offer_raises(allegro_logged_page):
    in_basket = {i["offerId"] for i in basket.show(allegro_logged_page)["items"]}
    assert "999999999999" not in in_basket
    with pytest.raises(basket.BasketError):
        basket.remove(allegro_logged_page, "999999999999")
