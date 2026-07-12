"""Modele danych katalogu rossmann.pl."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_PRICE_PER_UNIT_RE = re.compile(r"=\s*([\d\s]+(?:,\d+)?)\s*z[łl]")

# "100 ml = 2,80 zł" -> baza (ilość + jednostka) i kwota
_PRICE_PER_UNIT_FULL_RE = re.compile(
    r"([\d\s]+(?:,\d+)?)\s*([a-ząćęłńóśźż.]+)\s*=\s*([\d\s]+(?:,\d+)?)\s*z[łl]",
    re.IGNORECASE,
)

# jednostka sklepu -> (jednostka bazowa, mnożnik do bazy); normalizujemy do zł za 1 l / 1 kg / 1 szt.
_UNIT_TO_BASE = {
    "ml": ("l", 0.001),
    "l": ("l", 1.0),
    "g": ("kg", 0.001),
    "kg": ("kg", 1.0),
    "szt": ("szt.", 1.0),
}


def _pln(text: str) -> float:
    return float(text.replace(" ", "").replace(",", "."))


def _picture(d: dict[str, Any]) -> str | None:
    """URL zdjęcia: wprost z pola (historia zamówień) albo z listy pictures (katalog)."""
    if d.get("picture"):
        return d["picture"]
    pictures = d.get("pictures")
    if isinstance(pictures, list) and pictures:
        first = pictures[0]
        if isinstance(first, dict):
            return first.get("square") or first.get("small") or first.get("medium")
    return None


def _eans(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


@dataclass
class Product:
    id: int
    name: str
    brand: str | None = None
    caption: str | None = None
    price: float | None = None
    old_price: float | None = None
    price_per_unit: str | None = None
    unit: str | None = None
    ean: list[str] = field(default_factory=list)
    availability: str | None = None
    category: str | None = None
    url: str | None = None
    promotion: str | None = None
    rating: float | None = None
    total_reviews: int | None = None
    picture: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> "Product":
        promotion = d.get("promotion")
        if isinstance(promotion, dict):
            promotion = promotion.get("type")
        elif isinstance(d.get("promotions"), list) and d["promotions"]:
            first = d["promotions"][0]
            promotion = first.get("type") if isinstance(first, dict) else None
        name = " ".join(filter(None, [d.get("brand"), (d.get("name") or "").strip()]))
        return cls(
            id=d["id"],
            name=name or str(d["id"]),
            brand=d.get("brand"),
            caption=d.get("caption"),
            price=d.get("price"),
            old_price=d.get("oldPrice"),
            price_per_unit=d.get("pricePerUnit"),
            unit=d.get("unit"),
            ean=_eans(d.get("eanNumber")),
            availability=d.get("availability"),
            category=d.get("category"),
            url=d.get("navigateUrl"),
            promotion=promotion,
            rating=d.get("averageRating"),
            total_reviews=d.get("totalReviews"),
            picture=_picture(d),
            raw=d,
        )

    @property
    def price_per_unit_value(self) -> float | None:
        """Kwota w zł z pola typu "100 ml = 6,33 zł" (do porównań w obrębie tej samej bazy jednostki)."""
        if not self.price_per_unit:
            return None
        m = _PRICE_PER_UNIT_RE.search(self.price_per_unit)
        if not m:
            return None
        return _pln(m.group(1))

    @property
    def price_per_unit_normalized(self) -> dict[str, Any] | None:
        """Cena znormalizowana do zł za 1 l / 1 kg / 1 szt.: {"value", "unit"}.

        Sklep miesza bazy ("100 ml = 2,80 zł" vs "1 l = 16,81 zł") — po normalizacji
        obie dają zł/l i są porównywalne. None dla jednostek spoza mapy (np. m²).
        """
        if not self.price_per_unit:
            return None
        m = _PRICE_PER_UNIT_FULL_RE.search(self.price_per_unit)
        if not m:
            return None
        base = _UNIT_TO_BASE.get(m.group(2).lower().rstrip("."))
        if base is None:
            return None
        base_unit, factor = base
        amount = _pln(m.group(1)) * factor
        if amount <= 0:
            return None
        return {"value": round(_pln(m.group(3)) / amount, 4), "unit": base_unit}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "brand": self.brand,
            "caption": self.caption,
            "price": self.price,
            "oldPrice": self.old_price,
            "pricePerUnit": self.price_per_unit,
            "pricePerUnitValue": self.price_per_unit_value,
            "pricePerUnitNormalized": self.price_per_unit_normalized,
            "unit": self.unit,
            "ean": self.ean,
            "availability": self.availability,
            "category": self.category,
            "url": self.url,
            "promotion": self.promotion,
            "rating": self.rating,
            "totalReviews": self.total_reviews,
            "picture": self.picture,
        }


@dataclass
class Category:
    id: int
    name: str
    products_count: int | None = None
    children: list["Category"] = field(default_factory=list)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> "Category":
        return cls(
            id=d["id"],
            name=d["name"],
            products_count=d.get("productsCount"),
            children=[cls.from_api(c) for c in d.get("children") or []],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "productsCount": self.products_count,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class SearchResult:
    products: list[Product]
    total_count: int
    total_pages: int
    page: int
    categories: list[Category] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCount": self.total_count,
            "totalPages": self.total_pages,
            "page": self.page,
            "products": [p.to_dict() for p in self.products],
        }
