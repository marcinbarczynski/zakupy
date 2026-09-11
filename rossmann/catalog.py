"""Katalog produktów rossmann.pl.

Dane pochodzą z SSR: strony /szukaj i /produkty osadzają pełny stan
React Query w <script id="__NEXT_DATA__"> — parsujemy go zamiast
zgadywać wewnętrzne endpointy XHR.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

import httpx

from .http import ParseError
from .models import Category, Product, SearchResult

ORDERS = ("default", "priceAsc", "priceDesc", "newestFirst")

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

# Stan magazynowy z JSON-LD strony produktu. Pole "availability" z payloadu Synerise
# to flaga katalogowa ("produkt jest w ofercie"), nie stan — potrafi zwracać
# "available" dla produktu z zerowym stanem.
_SCHEMA_AVAIL_RE = re.compile(r'"availability":"https://schema\.org/(\w+)"')


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


def _page_stock(html: str) -> tuple[str | None, int | None]:
    """Realny stan ze strony produktu: (availability, available_quantity).

    Dwa niezależne sygnały — JSON-LD schema.org oraz courierStock magazynu wysyłkowego.
    Zwraca (None, None), gdy strona nie niesie żadnego z nich; wtedy wołający zostaje
    przy wartości z katalogu.
    """
    m = _SCHEMA_AVAIL_RE.search(html)
    availability = None
    if m:
        availability = "available" if m.group(1) == "InStock" else "unavailable"
    quantity = None
    try:
        # Strona produktu zagnieżdża pageProps dwukrotnie — pojedyncze daje null.
        page_props = _extract_next_data(html).get("props", {}).get("pageProps", {})
        data = ((page_props.get("pageProps") or {}).get("courierStock") or {}).get("data") or {}
        value = data.get("availableQuantity")
        if isinstance(value, int):
            quantity = value
    except (ParseError, json.JSONDecodeError, AttributeError):
        pass
    if availability is None and quantity is not None:
        availability = "available" if quantity > 0 else "unavailable"
    return availability, quantity


def _apply_stock(product: Product, html: str) -> Product:
    availability, quantity = _page_stock(html)
    if availability is not None:
        product.availability = availability
    product.available_quantity = quantity
    return product


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
    product = matches[0] if raw is None else Product.from_api(raw)
    return _apply_stock(product, resp.text)


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


def verify_stock(
    client: httpx.Client, products: list[Product], max_workers: int = 6
) -> list[Product]:
    """Uzupełnij produkty o realny stan ze stron produktowych (w miejscu).

    Jedno pobranie strony na produkt, równolegle. Produkty bez URL-a zostają
    nietknięte; błąd pobrania też nie psuje reszty — taki produkt zachowuje
    wartość z katalogu.
    """

    def fetch(product: Product) -> None:
        if not product.url:
            return
        try:
            resp = client.get(product.url)
            resp.raise_for_status()
        except httpx.HTTPError:
            return
        _apply_stock(product, resp.text)

    targets = [p for p in products if p.url]
    if targets:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            list(pool.map(fetch, targets))
    return products


def cheapest(
    client: httpx.Client,
    query: str | None = None,
    category_id: int | None = None,
    per_unit: bool = False,
    available_only: bool = True,
    limit: int = 10,
    scan_pages: int = 3,
    verify: bool = True,
) -> list[Product]:
    """Najtańsze produkty dla frazy/kategorii.

    Przy per_unit=True sortowanie odbywa się po cenie za jednostkę po stronie
    klienta — skanujemy scan_pages stron posortowanych rosnąco po cenie, więc
    wynik jest przybliżeniem wystarczającym dla listy zakupów.

    verify=True dokłada po jednym pobraniu strony produktu dla najlepszych
    kandydatów i odsiewa te bez stanu magazynowego — katalog sam z siebie zwraca
    produkty chwilowo niedostępne jako "available".
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
    if verify:
        # Weryfikujemy zapas nad limit, bo część kandydatów odpadnie — sprawdzanie
        # dopiero po przycięciu zwracałoby mniej wyników niż limit.
        collected = verify_stock(client, collected[: limit * 2])
        if available_only:
            collected = [p for p in collected if p.availability == "available"]
    return collected[:limit]
