"""Modele danych listingu allegro.pl.

Specyfika allegro: ten sam produkt sprzedaje wielu sprzedawców, często w innych
krotnościach (1 szt. vs zestaw 3 szt.), więc porównywalna jest dopiero cena
jednostkowa — najlepiej z uwzględnieniem dostawy. Oferty Smart przy koszyku
od 49,90 zł mają dostawę darmową, stąd tryb "smart" liczy je bez kosztu dostawy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SMART_THRESHOLD_PLN = 49.90

# "26,14 zł/l", "0,01 zł/ml", "1,24 zł/100ml", "1,23 zł/szt."
_PRICE_PER_UNIT_RE = re.compile(
    r"([\d\s\xa0]+(?:[.,]\d+)?)\s*zł\s*/\s*(\d+)?\s*([a-ząćęłńóśźż²\.]+)",
    re.IGNORECASE,
)

# jednostka z etykiety -> (jednostka bazowa, mnożnik na 1 bazową): zł/ml * 1000 = zł/l
_LABEL_UNIT_TO_BASE = {
    "ml": ("l", 1000.0),
    "l": ("l", 1.0),
    "g": ("kg", 1000.0),
    "kg": ("kg", 1.0),
    "szt": ("szt.", 1.0),
    "m²": ("m²", 1.0),
    "m2": ("m²", 1.0),
}

# fallback z tytułu: "3x750ml", "4 x 1L", "9 x 2 rolki", "ZESTAW 6 SZT", "500 ml"
_PACK_X_RE = re.compile(
    r"(\d+)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(ml|l|g|kg|rolek|rolki|rolka)\b", re.IGNORECASE
)
_PACK_COUNT_RE = re.compile(r"(\d+)\s*(?:szt|sztuk|pack|pak)\b", re.IGNORECASE)
# "4x" oderwane od pojemności ("4x Domestos 1L", "Domestos 1L x4")
_PACK_PREFIX_RE = re.compile(r"(?:^|[\s,(])(\d{1,2})\s*[x×](?![\d.,])", re.IGNORECASE)
# "x4" na końcu/luzem; NIE "x 90 listków" (liczba z własną jednostką słowną)
_PACK_SUFFIX_RE = re.compile(r"[x×]\s*(\d{1,2})\b(?![\d.,]|\s*[a-ząćęłńóśźż])", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|l|g|kg|rolek|rolki|rolka)\b", re.IGNORECASE)

_UNIT_TO_BASE = {
    "ml": ("l", 0.001),
    "l": ("l", 1.0),
    "g": ("kg", 0.001),
    "kg": ("kg", 1.0),
    # papier: sprzedawcy w "zł/szt." liczą raz listek, raz rolkę — rolka z tytułu
    # jest jedyną wiarygodną jednostką
    "rolek": ("rolka", 1.0),
    "rolki": ("rolka", 1.0),
    "rolka": ("rolka", 1.0),
}


def _pln(text: str) -> float:
    return float(text.replace(" ", "").replace("\xa0", "").replace(",", "."))


def _amount_plausible(amount: float, unit: str) -> bool:
    """Realny zakres ilości towaru w jednej ofercie (chroni przed literówkami/bzdurami)."""
    if amount <= 0:
        return False
    if unit in ("szt.", "rolka"):
        return 0.5 <= amount <= 5000
    return 0.005 <= amount <= 60  # l / kg / m²


def _amount(d: Any) -> float | None:
    if isinstance(d, dict) and d.get("amount") is not None:
        try:
            return float(d["amount"])
        except (TypeError, ValueError):
            return None
    return None


def _label_texts(node: Any) -> list[str]:
    """Teksty z allegrowych struktur labels: [{labelParts: [{text: ...}, ...]}, ...]."""
    texts: list[str] = []
    if isinstance(node, list):
        for label in node:
            for part in (label or {}).get("labelParts") or []:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(part["text"])
    return texts


def pack_from_title(title: str) -> dict[str, Any] | None:
    """Łączna ilość towaru z tytułu oferty: {"amount", "unit" (l/kg/szt.)}.

    "Domestos 3x750ml" -> 2.25 l; "Zestaw 6 szt" -> 6 szt.; "500 ml" -> 0.5 l.
    Heurystyka do porównań, gdy sprzedawca nie podał ceny jednostkowej.
    """
    m = _PACK_X_RE.search(title)
    if m:
        base_unit, factor = _UNIT_TO_BASE[m.group(3).lower()]
        return {"amount": int(m.group(1)) * _pln(m.group(2)) * factor, "unit": base_unit}
    m = _AMOUNT_RE.search(title)
    count_m = (
        _PACK_COUNT_RE.search(title)
        or _PACK_PREFIX_RE.search(title)
        or _PACK_SUFFIX_RE.search(title)
    )
    count = int(count_m.group(1)) if count_m else None
    if m:
        base_unit, factor = _UNIT_TO_BASE[m.group(2).lower()]
        # "6 szt x 250 ml" / "4x Domestos 1L" / "250 ml zestaw 6 szt"
        return {"amount": _pln(m.group(1)) * factor * (count or 1), "unit": base_unit}
    if count:
        return {"amount": float(count), "unit": "szt."}
    return None


@dataclass
class Offer:
    offer_id: str
    title: str
    price: float | None = None
    price_with_delivery: float | None = None
    delivery_lowest: float | None = None
    smart: bool = False
    free_delivery: bool = False
    price_per_unit: str | None = None
    seller_login: str | None = None
    seller_rating: float | None = None
    seller_super: bool = False
    product_id: str | None = None
    product_name: str | None = None
    product_offers_count: int | None = None
    product_offers_url: str | None = None
    rating: float | None = None
    total_reviews: int | None = None
    sponsored: bool = False
    cart_available: bool = False
    stock: int | None = None
    url: str | None = None
    picture: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, e: dict[str, Any]) -> "Offer":
        shipping = e.get("shipping") or {}
        seller = e.get("seller") or {}
        details = e.get("productDetails") or {}
        page_link = e.get("productPageLink") or {}
        review_rating = ((e.get("productReview") or {}).get("rating")) or {}
        freebox = _label_texts((e.get("freebox") or {}).get("labels"))
        price_per_unit = next(iter(_label_texts(e.get("pricePerUnit"))), None)
        stock = (((e.get("picker") or {}).get("stock") or {}).get("availability") or {}).get("quantity")
        rating = review_rating.get("average")
        return cls(
            offer_id=str(e.get("offerId") or ""),
            title=((e.get("title") or {}).get("text") or "").strip(),
            price=_amount((e.get("price") or {}).get("mainPrice")),
            price_with_delivery=_amount(shipping.get("itemWithDelivery")),
            delivery_lowest=_amount(shipping.get("lowest")),
            smart=any("Smart" in t for t in freebox),
            free_delivery=bool(shipping.get("freeDelivery")),
            price_per_unit=price_per_unit,
            seller_login=seller.get("login"),
            seller_rating=seller.get("positiveFeedbackPercent"),
            seller_super=bool(seller.get("superSeller")),
            product_id=details.get("productId"),
            product_name=details.get("productName"),
            product_offers_count=e.get("productOffersCount"),
            product_offers_url=page_link.get("url"),
            rating=float(rating) if rating is not None else None,
            total_reviews=review_rating.get("count"),
            sponsored=bool(e.get("isSponsored")),
            cart_available=bool(e.get("cartAvailable")),
            stock=stock,
            url=e.get("url"),
            picture=e.get("mainThumbnail"),
            raw=e,
        )

    def _unit_price_from_label(self) -> dict[str, Any] | None:
        if not self.price_per_unit:
            return None
        m = _PRICE_PER_UNIT_RE.search(self.price_per_unit)
        if not m:
            return None
        base = _LABEL_UNIT_TO_BASE.get(m.group(3).lower().rstrip("."))
        if base is None:
            return None
        base_unit, factor = base
        base_qty = float(m.group(2)) if m.group(2) else 1.0  # "zł/100ml"
        return {"value": round(_pln(m.group(1)) * factor / base_qty, 4), "unit": base_unit}

    def _unit_price_from_title(self) -> dict[str, Any] | None:
        if self.price is None:
            return None
        pack = pack_from_title(self.title)
        if not pack or not _amount_plausible(pack["amount"], pack["unit"]):
            return None  # np. "1040 l" w tytule to literówka (1040 ml)
        return {"value": round(self.price / pack["amount"], 4), "unit": pack["unit"]}

    def _label_plausible(self, label: dict[str, Any]) -> bool:
        """Ilość towaru implikowana etykietą (cena / cena-za-jedn.) musi być realna.

        "0,01 zł/l" przy butelce za 5,24 zł implikowałoby 524 l — bzdura.
        """
        if self.price is None or label["value"] <= 0:
            return True  # bez ceny nie mamy jak zweryfikować
        return _amount_plausible(self.price / label["value"], label["unit"])

    @property
    def price_per_unit_normalized(self) -> dict[str, Any] | None:
        """{"value", "unit"}: z pola sprzedawcy ("26,14 zł/l") lub wyliczona z tytułu.

        Sprzedawcy potrafią wpisać w pole ceny jednostkowej bzdurę ("0,01 zł/l"
        przy 750 ml za 9,29 zł), więc etykietę sprawdzamy dwojako: implikowana
        ilość musi być realna, a gdy tytuł daje wyliczenie w tej samej jednostce
        różniące się >=2,5x — ufamy tytułowi.
        """
        label = self._unit_price_from_label()
        title = self._unit_price_from_title()
        if label and not self._label_plausible(label):
            return title  # None też jest lepsze niż śmieciowa etykieta
        if label and title:
            if title["unit"] == "rolka" and label["unit"] == "szt.":
                return title  # "zł/szt." przy papierze bywa od listka/rolki/opakowania
            if label["unit"] == title["unit"] and title["value"] > 0:
                ratio = label["value"] / title["value"]
                if ratio < 0.4 or ratio > 2.5:
                    return title
        return label or title

    def effective_price(self, smart_mode: bool = True) -> float | None:
        """Cena do porównań między sprzedawcami: z dostawą, chyba że dostawa darmowa.

        W trybie smart oferty Smart liczymy bez dostawy — użytkownik ma Allegro
        Smart, a koszyk z listy zakupowej przekracza próg 49,90 zł.
        """
        if self.price is None:
            return None
        if self.free_delivery or (smart_mode and self.smart):
            return self.price
        return self.price_with_delivery if self.price_with_delivery is not None else self.price

    def effective_unit_price(self, smart_mode: bool = True) -> dict[str, Any] | None:
        """Cena jednostkowa liczona od effective_price (proporcjonalnie do zł/jedn. sprzedawcy)."""
        per_unit = self.price_per_unit_normalized
        effective = self.effective_price(smart_mode)
        if per_unit is None or effective is None or not self.price:
            return None
        return {"value": round(per_unit["value"] * effective / self.price, 4), "unit": per_unit["unit"]}

    def to_dict(self) -> dict[str, Any]:
        return {
            "shop": "allegro",
            "offerId": self.offer_id,
            "title": self.title,
            "price": self.price,
            "priceWithDelivery": self.price_with_delivery,
            "deliveryLowest": self.delivery_lowest,
            "smart": self.smart,
            "freeDelivery": self.free_delivery,
            "pricePerUnit": self.price_per_unit,
            "pricePerUnitNormalized": self.price_per_unit_normalized,
            "effectivePrice": self.effective_price(),
            "effectiveUnitPrice": self.effective_unit_price(),
            "seller": {
                "login": self.seller_login,
                "positivePercent": self.seller_rating,
                "superSeller": self.seller_super,
            },
            "productId": self.product_id,
            "productName": self.product_name,
            "productOffersCount": self.product_offers_count,
            "productOffersUrl": self.product_offers_url,
            "rating": self.rating,
            "totalReviews": self.total_reviews,
            "sponsored": self.sponsored,
            "cartAvailable": self.cart_available,
            "stock": self.stock,
            "url": self.url,
            "picture": self.picture,
        }


@dataclass
class SearchResult:
    offers: list[Offer]
    total_count: int | None = None
    products_count: int | None = None
    last_page: int | None = None
    page: int = 1
    search_phrase: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCount": self.total_count,
            "productsCount": self.products_count,
            "lastPage": self.last_page,
            "page": self.page,
            "searchPhrase": self.search_phrase,
            "offers": [o.to_dict() for o in self.offers],
        }
