---
name: zakupy
description: Robi zakupy z listy (JSON z pozycjami name+details) w rossmann.pl - dla każdej pozycji proponuje produkty (kupowane wcześniej + najtańsze za jednostkę), generuje interaktywną stronę z wyborem i dodaje zaznaczone do koszyka. Użyj gdy użytkownik chce zrobić zakupy z listy, np. "/zakupy example-list.json" albo "zrób zakupy z listy X".
---

# Zakupy z listy

Wejście: ścieżka do pliku JSON z listą zakupów (domyślnie `example-list.json` w cwd),
format: `[{"name": "...", "details": "..."}]`. `details` może nieść dodatkowe wymagania
(marka, pojemność, sklep) — uwzględnij je przy doborze.

Wynik: strona na `http://localhost:8765` z propozycjami per pozycja; użytkownik zaznacza
produkty i klika przycisk, który dodaje je do koszyka na koncie rossmann.pl.

Wszystkie komendy CLI uruchamiaj z korzenia repo rossmann (tam gdzie `pyproject.toml`
z pakietem `rossmann`). Pliki robocze pisz do `out/` w korzeniu repo.

## Krok 1: historia zakupów (raz na przebieg)

```bash
uv run rossmann orders products --json > out/history.json
```

Agregat kupionych produktów: `id`, `brand`, `caption`, `timesBought`, `totalQuantity`,
`lastOrderDate`, `lastUnitPrice`, `picture`, `url`. Id są zgodne z katalogiem.

## Krok 2: kandydaci per pozycja listy

Pozycje wskazujące inny sklep (np. „allegro" w name/details) pomiń w wyszukiwaniu —
w danych strony ustaw `note: "poza Rossmannem — <sklep>"` i pustych kandydatów.

Dla pozostałych pozycji:

1. **Historia najpierw**: dopasuj semantycznie produkty z historii do pozycji
   (po brand/name/caption — sam oceń trafność, np. „Magiczna gąbka" ↔ „DOMOL Magic Pad
   magiczna gąbka"). Dla trafionych pobierz świeże dane:
   `uv run rossmann product <id> --json` (cena, dostępność, promocja, zdjęcie).
2. **Wyszukiwarka**: 1–2 zapytania na pozycję, frazy układaj z `name`+`details`:
   `uv run rossmann cheapest "<fraza>" --per-unit --limit 20 --json`.
   Odfiltruj wyniki nietrafne znaczeniowo (wyszukiwarka bywa szeroka).
   Gdy pozycja to liczba sztuk/rozmiar (worki 60L, chusteczki w paczkach), sprawdź
   `caption`/`unit` zamiast ślepo ufać frazie.
3. **Selekcja** (~5 kandydatów): najpierw kupowane wcześniej, potem najtańsze wg
   `pricePerUnitNormalized` (zł za 1 l / 1 kg / 1 szt. — porównuj tylko w tej samej
   jednostce). Pokazuj wyłącznie `availability == "available"`, z dwoma wyjątkami,
   które pokazuj jako `disabled: true, disabledReason: "niedostępny"`:
   - produkt konkretnie wskazany na liście (marka/nazwa w name/details),
   - produkt często kupowany (`timesBought >= 2`).
   Cel: użytkownik robi zakupy raz w miesiącu i ma zobaczyć „płyn, który zawsze
   kupujemy", nawet gdy chwilowo niedostępny — obok dostępnych alternatyw.

Batchuj wywołania CLI (kilka `&` + `wait`, wyjścia do plików w `out/`), zamiast
odpalać po jednym.

## Krok 3: dane strony — `out/data.json`

Schemat niezależny od sklepu (przyszłe sklepy = kolejne wartości `shop`):

```json
{
  "generatedAt": "2026-07-12T12:00:00",
  "listName": "example-list",
  "positions": [
    {
      "name": "...", "details": "...",
      "note": "poza Rossmannem — allegro (opcjonalnie)",
      "candidates": [
        {
          "shop": "rossmann", "id": 123, "fullName": "MARKA nazwa", "caption": "...",
          "price": 12.49, "oldPrice": null, "promotion": null,
          "pricePerUnit": "1 l = 8,33 zł",
          "pricePerUnitNormalized": {"value": 8.33, "unit": "l"},
          "unit": "1,5 l", "picture": "https://...", "url": "https://...",
          "rating": 4.6, "totalReviews": 123, "availability": "available",
          "disabled": false, "disabledReason": null,
          "bought": {"times": 2, "lastDate": "2026-06-17"}
        }
      ]
    }
  ]
}
```

`url` zawsze absolutny (katalog zwraca względne — doklej `https://www.rossmann.pl`).
`bought: null` gdy produkt nie występuje w historii. `promotion` przepisz na czytelną
etykietę (typ `"rossmann"` → `"promocja"`, `"mega"` → `"MEGA cena"`) — surowy typ
`"rossmann"` myliłby się na stronie z chipem sklepu.

## Krok 4: serwer

```bash
uv run python .claude/skills/zakupy/scripts/serve.py --data out/data.json --port 8765
```

Uruchom w tle, sprawdź `curl -s localhost:8765 | head -1`, podaj użytkownikowi link.
Serwer renderuje `assets/template.html` z wstrzykniętymi danymi, a `POST /api/cart`
dodaje zaznaczone produkty przez `uv run rossmann basket add <id> --qty <n>`
(dispatch po polu `shop` — nowy sklep to nowa komenda w `serve.py`).
