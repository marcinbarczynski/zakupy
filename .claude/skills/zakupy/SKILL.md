---
name: zakupy
description: Robi zakupy z listy (JSON z pozycjami name+details) w rossmann.pl i allegro.pl - dla każdej pozycji proponuje produkty (kupowane wcześniej + najtańsze za jednostkę), generuje interaktywną stronę z wyborem i dodaje zaznaczone do koszyków. Użyj gdy użytkownik chce zrobić zakupy z listy, np. "/zakupy example-list.json" albo "zrób zakupy z listy X".
---

# Zakupy z listy

Wejście: ścieżka do pliku JSON z listą zakupów (domyślnie `example-list.json` w cwd),
format: `[{"name": "...", "details": "..."}]`. `details` może nieść dodatkowe wymagania
(marka, pojemność, sklep) — uwzględnij je przy doborze.

Wynik: strona na `http://localhost:8765` z propozycjami per pozycja; użytkownik zaznacza
produkty i klika przycisk, który dodaje je do koszyków na kontach rossmann.pl / allegro.pl.

Wszystkie komendy CLI uruchamiaj z korzenia repo rossmann (tam gdzie `pyproject.toml`
z pakietami `rossmann` i `allegro`). Pliki robocze pisz do `out/` w korzeniu repo.

**Uwaga do CLI allegro**: każde wywołanie steruje przeglądarką na trwałym profilu —
wywołania `allegro ...` odpalaj WYŁĄCZNIE sekwencyjnie (nigdy `&`/równolegle; profil
znosi jedną instancję naraz) i licz się z ~5–10 s na wywołanie. Komendy `rossmann`
można batchować jak dotąd.

## Krok 1: historia zakupów (raz na przebieg)

```bash
uv run rossmann orders products --json > out/history.json
uv run allegro orders products --json > out/allegro-history.json
```

Agregat kupionych produktów rossmann: `id`, `brand`, `caption`, `timesBought`,
`totalQuantity`, `lastOrderDate`, `lastUnitPrice`, `picture`, `url` (id zgodne
z katalogiem). Allegro analogicznie, tylko klucz oferty to `offerId` + `seller`.

## Krok 2: kandydaci per pozycja listy

Sklep domyślny to rossmann; pozycję szukaj w allegro gdy (a) name/details wskazuje
allegro, (b) to produkt spożywczy/specjalistyczny spoza asortymentu drogerii, albo
(c) w rossmannie brak sensownych trafień. Pozycje wskazujące jeszcze inny sklep pomiń —
`note: "poza obsługiwanymi sklepami — <sklep>"` i puści kandydaci.

Dla pozycji rossmann:

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

Batchuj wywołania CLI rossmann (kilka `&` + `wait`, wyjścia do plików w `out/`),
zamiast odpalać po jednym.

Dla pozycji allegro (sekwencyjnie!):

1. **Historia najpierw**: dopasuj pozycję do `out/allegro-history.json`; trafione
   oferty odśwież przez `uv run allegro offers <productId> --json` (inni sprzedawcy
   tego samego produktu) albo pokaż wprost z historii.
2. **Wyszukiwarka**: `uv run allegro cheapest "<fraza>" --limit 10 --json > out/a/<n>.json`.
   Ranking jest już po **efektywnej cenie jednostkowej** (`effectiveUnitPrice`):
   oferty Smart liczone bez dostawy, pozostałe z dostawą.
3. **Specyfika allegro przy selekcji (~5 kandydatów)**:
   - ten sam produkt sprzedaje wielu sprzedawców w różnych krotnościach (1 szt. vs
     zestaw 3 szt.) — porównuj po `effectiveUnitPrice`, nie po `price`;
   - **preferuj oferty `smart: true`** — użytkownik ma Allegro Smart i przy koszyku
     od 49,90 zł dostawa ofert Smart jest darmowa; dla ofert nie-Smart uczciwą ceną
     jest `priceWithDelivery`;
   - `sponsored: true` pokazuj tylko gdy realnie najtańsze (to reklamy);
   - sprawdzaj sensowność `effectiveUnitPrice` — sprzedawcy wpisują błędne ceny
     jednostkowe (CLI koryguje je z tytułu, ale tytuły też bywają mętne);
   - zwracaj uwagę na `seller.positivePercent` (unikaj < 97%).

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

`url` zawsze absolutny (katalog rossmann zwraca względne — doklej
`https://www.rossmann.pl`; allegro zwraca absolutne). `bought: null` gdy produkt nie
występuje w historii. `promotion` przepisz na czytelną etykietę (typ `"rossmann"` →
`"promocja"`, `"mega"` → `"MEGA cena"`) — surowy typ `"rossmann"` myliłby się na
stronie z chipem sklepu.

Mapowanie kandydata allegro na schemat: `shop: "allegro"`, `id` = `offerId` (string),
`fullName` = `title`, `caption` = `"@<seller.login> · Smart, dostawa 0 zł od 49,90"`
albo `"@<seller.login> · +<deliveryLowest> zł dostawa"`, `price`, `pricePerUnitNormalized`
= `effectiveUnitPrice`, `promotion`: `"Smart"` dla ofert Smart, `availability`:
`"available"` gdy `cartAvailable`, `bought` z `out/allegro-history.json`.

Po zbudowaniu `data.json` sprawdź: jeśli suma zaznaczalnych pozycji Smart z allegro
może nie przekroczyć 49,90 zł, dodaj pozycjom allegro notkę, że poniżej tego progu
dostawa Smart nie będzie darmowa.

## Krok 4: serwer

```bash
uv run python .claude/skills/zakupy/scripts/serve.py --data out/data.json --port 8765
```

Uruchom w tle, sprawdź `curl -s localhost:8765 | head -1`, podaj użytkownikowi link.
Serwer renderuje `assets/template.html` z wstrzykniętymi danymi, a `POST /api/cart`
dodaje zaznaczone produkty przez `uv run <sklep> basket add <id> --qty <n>`
(dispatch po polu `shop` w `_SHOP_COMMANDS` w `serve.py`; obsługiwane: rossmann,
allegro — pozycje allegro dodają się wolniej, bo CLI steruje przeglądarką).
