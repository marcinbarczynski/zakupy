"""Koszyk allegro.pl — operacje przez stronę /koszyk i strony ofert.

Stan koszyka czytamy z osadzonego JSON-a "cartData"; dodawanie klika
formularz na stronie oferty (submit "do koszyka" przy #quantityInput —
nie mylić z upsellowym "Dodaj zestaw do koszyka"). Usuwanie klika przycisk
"Usuń przedmiot ..." w wierszu danej oferty. Ustalone 2026-07-12.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from .browser import BASE_URL, AllegroError, ParseError, goto

if TYPE_CHECKING:
    from playwright.sync_api import Page

_CART_URL = BASE_URL + "/koszyk"


class BasketError(AllegroError):
    """Problem z koszykiem."""


def _price(d: Any) -> float | None:
    if isinstance(d, dict) and d.get("amount") is not None:
        try:
            return float(d["amount"])
        except (TypeError, ValueError):
            return None
    return None


def _cart_data(page: "Page") -> dict[str, Any]:
    payload = page.evaluate(
        """() => {
            for (const s of document.querySelectorAll('script[type="application/json"]')) {
                const t = s.textContent || '';
                if (t.includes('"cartData"')) return t;
            }
            return null;
        }"""
    )
    if payload is None:
        raise ParseError("brak danych koszyka na stronie /koszyk (zmiana frontu?)")
    try:
        return json.loads(payload)["cartData"]
    except (json.JSONDecodeError, KeyError) as e:
        raise ParseError(f"niepoprawne dane koszyka: {e}") from e


def _parse_cart(data: dict[str, Any]) -> dict[str, Any]:
    cart = data.get("cart") or {}
    items: list[dict[str, Any]] = []
    for group in cart.get("groups") or []:
        seller = ((group.get("seller") or {}).get("login"))
        for item in group.get("items") or []:
            offer = next(iter(item.get("offers") or []), {})
            items.append(
                {
                    "offerId": offer.get("id"),
                    "title": offer.get("name"),
                    "quantity": (item.get("quantity") or {}).get("selected"),
                    "unitPrice": _price(item.get("unitPrice")),
                    "price": _price(item.get("price")),
                    "seller": seller,
                    "url": offer.get("url"),
                    "available": item.get("available", True),
                }
            )
    total = sum(i["price"] for i in items if i["price"] is not None)
    return {
        "items": items,
        "totalPrice": round(total, 2),
        # cart.prices.total obejmuje tylko zaznaczone pozycje, stąd osobno:
        "selectedTotal": _price((cart.get("prices") or {}).get("total")),
        "groups": len(cart.get("groups") or []),
    }


def show(page: "Page") -> dict[str, Any]:
    goto(page, _CART_URL)
    return _parse_cart(_cart_data(page))


def add(page: "Page", offer_id: str, quantity: int = 1) -> str:
    """Dodaj ofertę do koszyka; zwraca tytuł oferty. Weryfikuje stan na /koszyk."""
    before = {i["offerId"]: i["quantity"] for i in show(page)["items"]}

    goto(page, f"{BASE_URL}/oferta/{offer_id}")
    qty_input = page.locator("#quantityInput")
    if not qty_input.count():
        raise BasketError(f"oferta {offer_id}: brak formularza zakupu (zakończona/wariantowa?)")
    if quantity != 1:
        qty_input.fill(str(quantity))
        page.wait_for_timeout(300)
    title = (page.locator("h1").first.text_content() or "").strip() or offer_id
    # widoczny "dodaj do koszyka"; omijamy upsellowy "Dodaj zestaw do koszyka"
    button = (
        page.locator("button:visible")
        .filter(has_text=re.compile("do koszyka", re.I))
        .filter(has_not_text=re.compile("zestaw", re.I))
    )
    if not button.count():
        raise BasketError(f"oferta {offer_id}: brak przycisku 'dodaj do koszyka'")
    button.first.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1_500)

    after = {i["offerId"]: i["quantity"] for i in show(page)["items"]}
    if after.get(offer_id, 0) <= before.get(offer_id, 0) and offer_id not in after:
        raise BasketError(f"oferta {offer_id} nie pojawiła się w koszyku")
    return title


def _row_selector(offer_id: str) -> str:
    return f'xpath=//input[@id="number-picker.input.{offer_id}"]/ancestor::*[.//button[starts-with(@aria-label, "Usuń przedmiot")]][1]'


def remove(page: "Page", offer_id: str) -> None:
    goto(page, _CART_URL)
    row = page.locator(_row_selector(offer_id))
    if not row.count():
        raise BasketError(f"oferty {offer_id} nie ma w koszyku")
    row.first.locator('button[aria-label^="Usuń przedmiot"]:visible').first.click()
    try:
        page.wait_for_selector(f'[id="number-picker.input.{offer_id}"]', state="detached", timeout=10_000)
    except Exception as e:
        raise BasketError(f"nie udało się usunąć oferty {offer_id}: {e}") from e


def clear(page: "Page") -> int:
    """Usuń wszystkie pozycje; zwraca ich liczbę."""
    removed = 0
    while True:
        goto(page, _CART_URL)
        buttons = page.locator('button[aria-label^="Usuń przedmiot"]:visible')
        if not buttons.count():
            return removed
        buttons.first.click()
        page.wait_for_timeout(1_500)
        removed += 1
