"""Scenariusz 1: katalog na żywym API — wyszukiwanie, kategorie, szczegóły, cheapest.

Asercje na niezmienniki (struktura, relacje, monotoniczność), nie na konkretne
produkty/ceny, bo asortyment się zmienia.
"""

from __future__ import annotations

from rossmann import catalog


def test_search_returns_sane_products(client):
    result = catalog.search(client, query="szampon")
    assert result.total_count > 0
    assert result.total_pages >= 1
    assert result.products
    for p in result.products:
        assert p.id > 0
        assert p.name.strip()
        assert p.price is None or p.price > 0
        assert p.availability is not None
        assert p.url and p.url.startswith("/")


def test_search_price_asc_is_sorted(client):
    result = catalog.search(client, query="szampon", order="priceAsc")
    prices = [p.price for p in result.products if p.price is not None]
    assert len(prices) > 3
    assert prices == sorted(prices)


def test_search_price_filter_applies(client):
    result = catalog.search(client, query="szampon", price_from=10, price_to=20)
    priced = [p for p in result.products if p.price is not None]
    assert priced
    for p in priced:
        assert 10 <= p.price <= 20


def test_search_nonsense_query_returns_empty_not_error(client):
    result = catalog.search(client, query="xyzzy123niematakiego")
    assert result.total_count == 0
    assert result.products == []


def test_categories_tree_is_nested(client):
    cats = catalog.categories(client)
    assert len(cats) >= 5
    names = {c.name for c in cats}
    assert "Włosy" in names or "Perfumy" in names
    assert any(c.children for c in cats), "drzewo powinno mieć zagnieżdżenia"
    with_children = next(c for c in cats if c.children)
    assert all(ch.id > 0 and ch.name for ch in with_children.children)


def test_category_search_stays_in_category(client):
    cats = catalog.categories(client)
    hair = next(c for c in cats if c.name == "Włosy")
    result = catalog.search(client, category_id=hair.id)
    assert result.total_count > 0
    in_category = [p for p in result.products if p.category and p.category.startswith("Włosy")]
    assert len(in_category) >= len(result.products) // 2


def test_product_details_consistent_with_search(client):
    found = catalog.search(client, query="szampon").products[0]
    detail = catalog.product_details(client, found.id)
    assert detail.id == found.id
    assert detail.price is not None
    assert detail.ean, "strona produktu powinna dać EAN-y"


def test_cheapest_sorted_by_price(client):
    products = catalog.cheapest(client, query="szampon", limit=5)
    assert products
    prices = [p.price for p in products]
    assert prices == sorted(prices)
    assert all(p.availability == "available" for p in products)


def test_cheapest_per_unit_sorted(client):
    products = catalog.cheapest(client, query="mydło w płynie", per_unit=True, limit=5)
    assert products
    normalized = [p.price_per_unit_normalized for p in products]
    assert all(n is not None for n in normalized)
    keys = [(n["unit"], n["value"]) for n in normalized]
    assert keys == sorted(keys)


def test_per_unit_normalization_against_live_data(client):
    """Bazy "100 ml" i "1 l" muszą po normalizacji dawać porównywalne zł/l,
    spójne z ceną i pojemnością produktu."""
    result = catalog.search(client, query="płyn do prania")
    liquids = [p for p in result.products if p.price_per_unit_normalized]
    assert len(liquids) > 3
    for p in liquids:
        n = p.price_per_unit_normalized
        assert n["unit"] in ("l", "kg", "szt.")
        assert n["value"] > 0
        # sanity: litr płynu do prania nie kosztuje mniej niż 1 zł ani więcej niż 500 zł
        if n["unit"] == "l":
            assert 1 < n["value"] < 500


def test_per_unit_parser_examples():
    """Czyste przykłady parsera — bez sieci, ale to nadal realne formaty sklepu."""
    from rossmann.models import Product

    cases = {
        "100 ml = 2,80 zł": {"value": 28.0, "unit": "l"},
        "1 l = 16,81 zł": {"value": 16.81, "unit": "l"},
        "100 g = 1,50 zł": {"value": 15.0, "unit": "kg"},
        "1 kg = 9,99 zł": {"value": 9.99, "unit": "kg"},
        "1 szt. = 0,55 zł": {"value": 0.55, "unit": "szt."},
        "1 m² = 3,00 zł": None,  # jednostka spoza mapy — brak normalizacji
        None: None,
    }
    for text, expected in cases.items():
        p = Product(id=1, name="x", price_per_unit=text)
        assert p.price_per_unit_normalized == expected, text


def test_product_details_reports_real_stock(client):
    """Szczegóły produktu niosą realny stan ze strony, nie flagę katalogową.

    Katalog (payload Synerise) zwraca "available" także dla produktów chwilowo
    niedostępnych — stan bierzemy z JSON-LD i courierStock strony produktu.
    """
    products = catalog.cheapest(client, query="szampon", limit=3, verify=False)
    assert products
    for p in products:
        detailed = catalog.product_details(client, p.id)
        assert detailed.availability in ("available", "unavailable")
        assert detailed.available_quantity is None or detailed.available_quantity >= 0
        if detailed.availability == "available":
            assert detailed.available_quantity is None or detailed.available_quantity > 0
        else:
            assert detailed.available_quantity in (None, 0)


def test_cheapest_verify_stock_filters_out_of_stock(client):
    """Z weryfikacją stanu w wynikach zostają tylko produkty faktycznie do kupienia."""
    verified = catalog.cheapest(
        client, query="płyn do prania", per_unit=True, limit=5, verify=True
    )
    assert verified
    for p in verified:
        assert p.availability == "available"
        assert p.available_quantity is None or p.available_quantity > 0


def test_cheapest_without_verification_skips_stock_lookup(client):
    """Bez weryfikacji nie ma dodatkowych pobrań — stan zostaje nieustalony."""
    raw = catalog.cheapest(client, query="płyn do prania", per_unit=True, limit=5, verify=False)
    assert raw
    assert all(p.available_quantity is None for p in raw)
