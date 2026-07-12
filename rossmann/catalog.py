"""Katalog produktów rossmann.pl.

Dane pochodzą z SSR: strony /szukaj i /produkty osadzają pełny stan
React Query w <script id="__NEXT_DATA__"> — parsujemy go zamiast
zgadywać wewnętrzne endpointy XHR.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

import httpx

from .http import ParseError
from .models import Category, Product, SearchResult

ORDERS = ("default", "priceAsc", "priceDesc", "newestFirst")

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _extract_next_data(html: str) -> dict[str, Any]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise ParseError("Brak __NEXT_DATA__ w odpowiedzi — zmienił się frontend rossmann.pl?")
    return json.loads(m.group(1))


def _iter_dehydrated_queries(node: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Znajdź wszystkie wpisy react-query (obiekty z queryKey + state) w drzewie pageProps."""
    if depth > 8:
        return
    if isinstance(node, dict):
        if "queryKey" in node and "state" in node:
            yield node
        else:
            for v in node.values():
                yield from _iter_dehydrated_queries(v, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_dehydrated_queries(v, depth + 1)


def _products_payload(next_data: dict[str, Any]) -> dict[str, Any]:
    for q in _iter_dehydrated_queries(next_data.get("props", {})):
        key = q.get("queryKey")
        if isinstance(key, list) and key and key[0] == "syneriseProducts":
            data = (q.get("state") or {}).get("data")
            if isinstance(data, dict) and "items" in data:
                return data
    raise ParseError(
        "Nie znaleziono danych produktów (queryKey 'syneriseProducts') w __NEXT_DATA__."
    )


def search(
    client: httpx.Client,
    query: str | None = None,
    category_id: int | None = None,
    page: int = 1,
    order: str = "default",
    price_from: float | None = None,
    price_to: float | None = None,
) -> SearchResult:
    if order not in ORDERS:
        raise ValueError(f"order musi być jednym z {ORDERS}")
    params: dict[str, Any] = {"Page": page}
    if query:
        params["Search"] = query
    if category_id:
        params["CategoryId"] = category_id
    if order != "default":
        params["Order"] = order
    if price_from is not None:
        params["PriceFrom"] = price_from
    if price_to is not None:
        params["PriceTo"] = price_to
    path = "/szukaj" if query else "/produkty"
    resp = client.get(path, params=params)
    # Frontend zwraca status 404 dla wyszukiwania bez wyników — strona nadal
    # zawiera pełny (pusty) payload produktów, więc parsujemy ją normalnie.
    if resp.status_code != 404:
        resp.raise_for_status()
    data = _products_payload(_extract_next_data(resp.text))
    filters = data.get("filters") or {}
    return SearchResult(
        products=[Product.from_api(i) for i in data.get("items") or []],
        total_count=data.get("totalCount") or 0,
        total_pages=data.get("totalPages") or 0,
        page=page,
        categories=[Category.from_api(c) for c in filters.get("categories") or []],
    )


def categories(client: httpx.Client) -> list[Category]:
    """Pełne drzewo kategorii sklepu (z filtrów strony /produkty)."""
    return search(client).categories


def product_details(client: httpx.Client, product_id: int) -> Product:
    """Szczegóły produktu: znajdź po ID przez wyszukiwarkę, potem pobierz stronę produktu."""
    found = search(client, query=str(product_id))
    matches = [p for p in found.products if p.id == product_id]
    if not matches:
        raise ParseError(f"Produkt {product_id} nie istnieje albo nie jest widoczny w wyszukiwarce.")
    url = matches[0].url
    if not url:
        return matches[0]
    resp = client.get(url)
    resp.raise_for_status()
    raw = _find_product_dict(_extract_next_data(resp.text).get("props", {}), product_id)
    if raw is None:
        return matches[0]
    return Product.from_api(raw)


def _find_product_dict(node: Any, product_id: int, depth: int = 0) -> dict[str, Any] | None:
    if depth > 8:
        return None
    if isinstance(node, dict):
        if node.get("id") == product_id and "price" in node and "name" in node:
            return node
        for v in node.values():
            r = _find_product_dict(v, product_id, depth + 1)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_product_dict(v, product_id, depth + 1)
            if r is not None:
                return r
    return None


def cheapest(
    client: httpx.Client,
    query: str | None = None,
    category_id: int | None = None,
    per_unit: bool = False,
    available_only: bool = True,
    limit: int = 10,
    scan_pages: int = 3,
) -> list[Product]:
    """Najtańsze produkty dla frazy/kategorii.

    Przy per_unit=True sortowanie odbywa się po cenie za jednostkę po stronie
    klienta — skanujemy scan_pages stron posortowanych rosnąco po cenie, więc
    wynik jest przybliżeniem wystarczającym dla listy zakupów.
    """
    collected: list[Product] = []
    page = 1
    while page <= scan_pages:
        result = search(client, query=query, category_id=category_id, page=page, order="priceAsc")
        collected.extend(result.products)
        if page >= result.total_pages:
            break
        page += 1
        if not per_unit and len(collected) >= limit * 2:
            break
    if available_only:
        collected = [p for p in collected if p.availability == "available"]
    if per_unit:
        # Znormalizowana cena (zł/l, zł/kg, zł/szt.) — bazy typu "100 ml" i "1 l"
        # są po niej porównywalne; grupujemy po jednostce bazowej, w ramach grupy rosnąco.
        collected = [p for p in collected if p.price_per_unit_normalized is not None]
        collected.sort(
            key=lambda p: (p.price_per_unit_normalized["unit"], p.price_per_unit_normalized["value"])
        )
    else:
        collected.sort(key=lambda p: (p.price is None, p.price))
    return collected[:limit]
