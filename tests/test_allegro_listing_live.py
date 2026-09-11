"""Scenariusze listingu allegro.pl: wyszukiwanie, sortowanie, cena jednostkowa, oferty produktu."""

from __future__ import annotations

import pytest

from allegro import listing
from allegro.models import Offer, pack_from_title


def test_search_returns_offers_with_prices(allegro_page):
    result = listing.search(allegro_page, "domestos zagęszczony")
    assert result.total_count and result.total_count > 10
    assert len(result.offers) >= 10
    priced = [o for o in result.offers if o.price is not None]
    assert len(priced) >= 10
    offer = priced[0]
    assert offer.offer_id.isdigit()
    assert offer.title
    assert offer.seller_login
    assert offer.url and offer.url.startswith("https://allegro.pl/")


def test_search_price_sort_monotonic(allegro_page):
    """order=p sortuje osobno sekcję wyróżnionych i zwykłych — każda ma być rosnąca."""
    result = listing.search(allegro_page, "domestos zagęszczony", sort="price")
    organic = [o for o in result.offers if o.price is not None and not o.sponsored]
    assert len(organic) >= 5
    for flag in (True, False):
        prices = [o.price for o in organic if bool(o.raw.get("promoted")) is flag]
        assert prices == sorted(prices), f"sekcja promoted={flag} powinna być rosnąca"


def test_search_price_filter(allegro_page):
    result = listing.search(allegro_page, "płyn do naczyń", price_from=10, price_to=30)
    in_range = [o for o in result.offers if o.price is not None and not o.sponsored]
    assert in_range
    assert all(10 <= o.price <= 30 for o in in_range)


def test_nonsense_query_no_error(allegro_page):
    """Allegro fuzzy-matchuje nawet losowe frazy — ma nie być wyjątku, wynik dowolny."""
    result = listing.search(allegro_page, "xqzvwrtplmk9847bzu")
    assert result.search_phrase == "xqzvwrtplmk9847bzu"
    assert isinstance(result.offers, list)


def test_generic_brand_query_redirect_handled(allegro_page):
    """Fraza "domestos" przekierowuje na stronę marki — CLI ma mimo to zwrócić oferty."""
    result = listing.search(allegro_page, "domestos")
    assert len(result.offers) >= 10


def test_product_offers_multiple_sellers(allegro_page):
    result = listing.search(allegro_page, "domestos zagęszczony", sort="price")
    productized = next(o for o in result.offers if (o.product_offers_count or 0) > 1)
    offers = listing.product_offers(allegro_page, productized.product_id)
    sellers = {o.seller_login for o in offers.offers if o.seller_login}
    assert len(sellers) > 1, "oferty produktu powinny pochodzić od wielu sprzedawców"


def test_unit_price_present_on_live_data(allegro_page):
    result = listing.search(allegro_page, "domestos zagęszczony 750")
    normalized = [o.price_per_unit_normalized for o in result.offers]
    with_unit = [n for n in normalized if n]
    assert len(with_unit) >= len(result.offers) // 2
    assert all(n["unit"] in ("l", "kg", "szt.", "m²") for n in with_unit)
    assert all(0 < n["value"] < 1000 for n in with_unit)


def test_cheapest_ranking_sane(allegro_page):
    offers = listing.cheapest(allegro_page, "domestos zagęszczony płyn wc", limit=8, scan_pages=1)
    assert offers
    values = [o.effective_unit_price()["value"] for o in offers if o.effective_unit_price()]
    assert values == sorted(values)
    # 2l/5l opakowania i multipacki powinny wygrywać z pojedynczą małą butelką
    assert values[0] < 10, f"najlepsza cena {values[0]} zł/l wygląda na zawyżoną"


# --- czysto offline'owe tabelki parserów (bez sieci) ---

_PACK_CASES = {
    "Domestos 3x750ml zagęszczony": (2.25, "l"),
    "4x Domestos płyn Przedłużona Moc 1L ZESTAW": (4.0, "l"),
    "DOMESTOS PROF. 5L": (5.0, "l"),
    "Kostki WC zestaw 6 szt": (6.0, "szt."),
    "Ludwik płyn 900 g cytryna": (0.9, "kg"),
    "Proszek 2 x 1,5 kg": (3.0, "kg"),
    "Velvet reczniki papierowe Ultra Strong 9 x 2 rolki": (18.0, "rolka"),
    "Ręcznik papierowy VELVET 2 rolki x 90 listków": (2.0, "rolka"),
    "Papier toaletowy Velvet 24 rolki": (24.0, "rolka"),
    "Papier toaletowy bez rozmiaru": None,
}


def test_pack_from_title_examples():
    for title, expected in _PACK_CASES.items():
        got = pack_from_title(title)
        if expected is None:
            assert got is None, title
        else:
            assert got is not None, title
            assert got["unit"] == expected[1], title
            assert abs(got["amount"] - expected[0]) < 1e-6, title


_LABEL_CASES = {
    "26,14\xa0zł/l": (26.14, "l"),
    "0,01 zł/ml": (10.0, "l"),
    "1,24 zł/100ml": (12.4, "l"),
    "5,00 zł/kg": (5.0, "kg"),
    "2,00 zł/szt.": (2.0, "szt."),
}


def test_unit_price_label_parser_examples():
    for label, (value, unit) in _LABEL_CASES.items():
        offer = Offer(offer_id="1", title="bez rozmiaru w tytule", price=None, price_per_unit=label)
        got = offer.price_per_unit_normalized
        assert got == {"value": value, "unit": unit}, label


def test_rolka_title_beats_ambiguous_szt_label():
    """"zł/szt." przy papierze bywa liczone od listka — tytuł z rolkami jest wiarygodniejszy."""
    offer = Offer(
        offer_id="1",
        title="Ręcznik papierowy VELVET 2 rolki x 90 listków",
        price=10.09,
        price_per_unit="0,11 zł/szt.",  # 0,11 za listek, nie za rolkę
    )
    got = offer.price_per_unit_normalized
    assert got == {"value": round(10.09 / 2, 4), "unit": "rolka"}


def test_garbage_unit_price_label_overridden_by_title():
    offer = Offer(
        offer_id="1",
        title="Domestos żel WC Lawenda 750ml",
        price=9.29,
        price_per_unit="0,01\xa0zł/l",  # sprzedawca wpisał bzdurę
    )
    got = offer.price_per_unit_normalized
    assert got and got["unit"] == "l"
    assert abs(got["value"] - 9.29 / 0.75) < 0.01


def test_effective_price_smart_mode():
    offer = Offer(offer_id="1", title="x 1l", price=10.0, price_with_delivery=20.0, smart=True)
    assert offer.effective_price(smart_mode=True) == 10.0
    assert offer.effective_price(smart_mode=False) == 20.0
    non_smart = Offer(offer_id="2", title="x 1l", price=10.0, price_with_delivery=20.0, smart=False)
    assert non_smart.effective_price(smart_mode=True) == 20.0
