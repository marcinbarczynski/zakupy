"""Wyszukiwanie ofert: strony /listing i /oferty-produktu (wspólny format danych).

Fraza generyczna (np. "domestos") bywa przekierowywana na stronę marki
/marka/<slug> bez listingu — wtedy ponawiamy z wymuszonym sortowaniem,
co omija przekierowanie.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from .browser import BASE_URL, ParseError, goto, listing_state
from .models import Offer, SearchResult

if TYPE_CHECKING:
    from playwright.sync_api import Page

# kody sortowania z parametru ?order= strony allegro.pl
SORT_MAP = {
    "relevance": None,
    "price": "p",
    "price-desc": "pd",
    "popularity": "m",
    "newest": "n",
}

_SKIP_ELEMENT_TYPES = {"banner", "label"}


def listing_url(
    query: str,
    order: str | None = None,
    price_from: float | None = None,
    price_to: float | None = None,
    page_num: int = 1,
) -> str:
    params = [f"string={quote(query)}"]
    if order:
        params.append(f"order={order}")
    if price_from is not None:
        params.append(f"price_from={price_from:g}")
    if price_to is not None:
        params.append(f"price_to={price_to:g}")
    if page_num > 1:
        params.append(f"p={page_num}")
    return f"{BASE_URL}/listing?" + "&".join(params)


def _parse_result(state: dict[str, Any], page_num: int) -> SearchResult:
    items = state.get("items") or {}
    elements = items.get("elements") or []
    offers = [
        Offer.from_api(e)
        for e in elements
        if e.get("type") not in _SKIP_ELEMENT_TYPES and e.get("offerId")
    ]
    meta = items.get("searchMeta") or {}
    return SearchResult(
        offers=offers,
        total_count=meta.get("totalCount"),
        products_count=meta.get("productsCount"),
        last_page=meta.get("lastAvailablePage"),
        page=page_num,
        search_phrase=items.get("searchPhrase"),
    )


def _fetch_listing(page: "Page", url: str, query: str | None, page_num: int) -> SearchResult:
    goto(page, url)
    try:
        state = listing_state(page)
    except ParseError:
        # przekierowanie na stronę marki/kampanii — wymuszenie order zwykle je omija
        if query is not None and "/listing" not in page.url:
            goto(page, listing_url(query, order="m", page_num=page_num))
            state = listing_state(page)
        else:
            raise
    return _parse_result(state, page_num)


def search(
    page: "Page",
    query: str,
    sort: str = "relevance",
    price_from: float | None = None,
    price_to: float | None = None,
    page_num: int = 1,
) -> SearchResult:
    url = listing_url(query, SORT_MAP[sort], price_from, price_to, page_num)
    return _fetch_listing(page, url, query, page_num)


def product_offers(page: "Page", product_id: str, sort: str = "price", page_num: int = 1) -> SearchResult:
    """Wszystkie oferty jednego produktu (mechanika "zobacz N ofert")."""
    url = f"{BASE_URL}/oferty-produktu/{product_id}"
    order = SORT_MAP[sort]
    params = ([f"order={order}"] if order else []) + ([f"p={page_num}"] if page_num > 1 else [])
    if params:
        url += "?" + "&".join(params)
    return _fetch_listing(page, url, None, page_num)


def _unit_group(unit: str) -> str:
    """Grupa porównawcza jednostki: rolka i szt. traktujemy razem (przy papierze
    sprzedawcy w "zł/szt." zwykle mają na myśli rolkę)."""
    return "szt." if unit in ("szt.", "rolka") else unit


def _dominant_unit(offers: list[Offer], smart_mode: bool) -> str | None:
    """Grupa jednostek, w której wyceniona jest większość ofert (zł/l vs zł/szt. są nieporównywalne)."""
    counts: dict[str, int] = {}
    for offer in offers:
        unit_price = offer.effective_unit_price(smart_mode)
        if unit_price:
            group = _unit_group(unit_price["unit"])
            counts[group] = counts.get(group, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _metric(offer: Offer, per_unit: bool, smart_mode: bool, dominant_unit: str | None = None) -> tuple:
    """Klucz sortowania: najpierw oferty porównywalne (cena/jedn. w dominującej
    grupie jednostek), potem pozostałe po cenie efektywnej, na końcu bez ceny."""
    effective = offer.effective_price(smart_mode)
    if effective is None:
        return (2, 0.0)
    if per_unit:
        unit_price = offer.effective_unit_price(smart_mode)
        if unit_price is not None and (
            dominant_unit is None or _unit_group(unit_price["unit"]) == dominant_unit
        ):
            return (0, unit_price["value"])
        return (1, effective)
    return (0, effective)


def cheapest(
    page: "Page",
    query: str,
    per_unit: bool = True,
    smart_mode: bool = True,
    limit: int = 10,
    scan_pages: int = 2,
    expand_products: int = 2,
) -> list[Offer]:
    """Najtańsze oferty dla frazy — po efektywnej cenie jednostkowej.

    Skanuje strony posortowane po cenie, a dla czołowych kart produktowych
    z wieloma ofertami dociąga /oferty-produktu, żeby porównać sprzedawców
    (najtańsza sztuka nie zawsze wygrywa z multipackiem po przeliczeniu).
    """
    pool: dict[str, Offer] = {}
    result = search(page, query, sort="price")
    for offer in result.offers:
        pool.setdefault(offer.offer_id, offer)
    for extra_page in range(2, scan_pages + 1):
        if result.last_page is None or extra_page > result.last_page:
            break
        for offer in search(page, query, sort="price", page_num=extra_page).offers:
            pool.setdefault(offer.offer_id, offer)

    dominant = _dominant_unit(list(pool.values()), smart_mode) if per_unit else None
    ranked = sorted(pool.values(), key=lambda o: _metric(o, per_unit, smart_mode, dominant))
    expanded = 0
    for offer in list(ranked[: limit * 2]):
        if expanded >= expand_products:
            break
        if offer.product_id and (offer.product_offers_count or 0) > 1:
            expanded += 1
            try:
                for other in product_offers(page, offer.product_id).offers:
                    pool.setdefault(other.offer_id, other)
            except ParseError:
                continue  # strona produktu bez listingu — zostają wyniki z wyszukiwania

    dominant = _dominant_unit(list(pool.values()), smart_mode) if per_unit else None
    ranked = sorted(pool.values(), key=lambda o: _metric(o, per_unit, smart_mode, dominant))
    return ranked[:limit]
