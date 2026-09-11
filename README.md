# rossmann + allegro — nieoficjalne interfejsy CLI do sklepów

Interfejsy do wyszukiwania produktów, sprawdzania cen i operowania na koszykach
kont rossmann.pl i allegro.pl. Pomyślane jako fundament pod skilla do robienia
list zakupów (konkretne produkty albo najtańsze z kategorii).

## Wymagania

- [uv](https://docs.astral.sh/uv/)
- plik `.rossmann` (rossmann) i `.allegro` (allegro) w korzeniu projektu
  (nie commitować! oba są w `.gitignore`):

```
EMAIL=twoj@email.pl
PASSWORD=twoje-haslo
```

- dla `allegro` dodatkowo: zainstalowany Google Chrome i **aktywna sesja
  graficzna** (CLI steruje prawdziwą przeglądarką — patrz niżej).

## Komendy

Każda komenda ma flagę `--json` ze stabilnym formatem pod automatyzację.
Kod wyjścia ≠ 0 i komunikat na stderr przy błędzie.

```bash
# Katalog (bez logowania)
uv run rossmann search "szampon" [--sort price|price-desc|newest] [--category ID] \
    [--min-price X] [--max-price Y] [--page N] [--limit N] [--json]
uv run rossmann categories [--tree] [--json]      # drzewo kategorii z ID
uv run rossmann product 182865 [--json]           # szczegóły produktu po ID
uv run rossmann cheapest "mydło w płynie" [--per-unit] [--category ID] \
    [--include-unavailable] [--limit N] [--json]  # najtańsze; --per-unit = wg ceny za 100ml/kg itd.

# Konto (dane z .rossmann, token cache'owany w ~/.cache/rossmann-cli/)
uv run rossmann login
uv run rossmann whoami [--json]

# Historia zamówień na koncie
uv run rossmann orders list [--limit N] [--json]        # zamówienia od najnowszego
uv run rossmann orders show 85098185 [--json]           # pełna lista produktów zamówienia
uv run rossmann orders products [--max-orders N] [--json]  # agregat kupionych produktów
                                                        # (ile razy, ile sztuk, kiedy ostatnio)

# Koszyk online na koncie
uv run rossmann basket show [--json]
uv run rossmann basket add 182865 --qty 2
uv run rossmann basket remove 182865
uv run rossmann basket clear
```

## Jak to działa

- **Katalog**: strony `/szukaj` i `/produkty` renderują się server-side (Next.js)
  i osadzają pełne dane produktów w `__NEXT_DATA__` — parsujemy je wprost
  (`rossmann/catalog.py`). Sortowanie/filtry (`Order=priceAsc`, `CategoryId`,
  `PriceFrom/To`) są obsługiwane przez serwer w parametrach URL.
- **Auth** (`rossmann/auth.py`): `POST /auth/token` z `{userName, password}` →
  bearer token (+ uniksowy `expiry`); odświeżanie `POST /auth/tokens/refreshment`;
  profil `GET /usr/api/user`. Token trzymany w pliku z prawami 600.
- **Koszyk** (`rossmann/basket.py`): `GET /shopping/api/v2/Cart/summary/details`,
  `POST/DELETE /basket/api/Basket/items` (tablice pełnych obiektów produktu/pozycji).
- **Zamówienia** (`rossmann/orders.py`): `GET /orders/order/grouped-history`
  (lista, paginacja `startIndex`), `GET /orders/order/online/{orderId}` (pełne
  produkty zamówienia; `id` produktów zgodne z katalogiem).
- **Cena za jednostkę**: sklep miesza bazy („100 ml = 2,80 zł" vs „1 l = 16,81 zł");
  `Product.price_per_unit_normalized` sprowadza je do zł za 1 l / 1 kg / 1 szt.
  i po tym sortuje `cheapest --per-unit`.
- Endpointy ustalone przez inspekcję ruchu przeglądarki (2026-07-11) — to
  nieoficjalne API, może się zmienić bez ostrzeżenia; parser wtedy głośno
  zgłosi `ParseError`.

## CLI `allegro`

```bash
# Listing (bez logowania)
uv run allegro search "domestos zagęszczony" [--sort relevance|price|price-desc|popularity|newest] \
    [--min-price X] [--max-price Y] [--page N] [--limit N] [--json]
uv run allegro offers <productId> [--json]   # wszystkie oferty produktu ("zobacz N ofert")
uv run allegro cheapest "płyn do wc" [--per-unit/--no-per-unit] [--smart/--no-smart] \
    [--limit N] [--scan-pages N] [--json]    # ranking po efektywnej cenie jednostkowej

# Konto (dane z .allegro; sesja w profilu przeglądarki + ~/.cache/allegro-cli/cookies.json)
uv run allegro login [--headful]   # --headful gdy trzeba przejść captchę/2FA w oknie
uv run allegro whoami [--json]
uv run allegro unblock             # okno do ręcznego odblokowania captchy DataDome

# Historia zakupów i koszyk
uv run allegro orders list [--limit N] [--json]
uv run allegro orders products [--max-orders N] [--json]
uv run allegro basket show [--json]
uv run allegro basket add <offerId> --qty 2
uv run allegro basket remove <offerId>
uv run allegro basket clear
```

### Jak działa `allegro` (i czym różni się od `rossmann`)

- **Allegro siedzi za DataDome** — goły HTTP dostaje 403/captchę, a **każdy wariant
  headless** (headless shell, `--headless=new`, headed pod Xvfb) jest wykrywany
  i dodatkowo flaguje profil (sprawdzone empirycznie 2026-07-12). Dlatego CLI
  odpala przez Playwrighta **prawdziwego, systemowego Chrome'a w trybie headed**
  na realnym pulpicie, z oknem odsuniętym poza ekran (`--window-position=3000,3000`).
  Wymaga to aktywnej sesji graficznej.
- **Dane listingu** są osadzone w HTML: `<script type="application/json">`
  z `__listing_StoreState.items.elements` (oferta: cena, `shipping.itemWithDelivery`,
  etykieta Smart, cena/jedn., sprzedawca, `productOffersCount`). Strona
  `/oferty-produktu/<uuid>` („zobacz N ofert" — wszyscy sprzedawcy jednego
  produktu) ma ten sam format, więc parser jest wspólny (`allegro/listing.py`).
  Fraza generyczna przekierowuje na stronę marki — CLI ponawia z wymuszonym
  sortowaniem, co omija przekierowanie.
- **Ceny porównywalne między sprzedawcami**: ten sam produkt bywa w różnych
  krotnościach (1 szt. za 5 zł vs 3 szt. za 12 zł), więc `cheapest` rankuje po
  **efektywnej cenie jednostkowej**: dla ofert Smart bez kosztu dostawy (konto ma
  Allegro Smart — dostawa darmowa od 49,90 zł koszyka), dla pozostałych wg ceny
  z dostawą. Cena/jedn. z etykiety sprzedawcy jest sanity-checkowana wyliczeniem
  z tytułu („3x750ml", „ZESTAW 6 SZT"), bo sprzedawcy wpisują tam bzdury
  (`allegro/models.py`).
- **Sesja konta**: profil przeglądarki w `~/.cache/allegro-cli/profile` trzyma
  cookie DataDome, a sesyjne cookies logowania (giną przy zamknięciu Chrome'a)
  CLI zapisuje/odtwarza samo w `~/.cache/allegro-cli/cookies.json` (prawa 600).
  Logowanie: formularz `/logowanie`; przejściówkę „uzupełnij telefon" CLI pomija.
- **Koszyk** (`allegro/basket.py`): stan z osadzonego JSON-a `cartData` na
  `/koszyk`; dodawanie klika widoczny przycisk „dodaj do koszyka" na stronie
  oferty (nie upsellowy „Dodaj zestaw…"), usuwanie — przycisk „Usuń przedmiot…"
  w wierszu oferty. **Zamówienia** (`allegro/orders.py`): osadzony JSON
  `myorders` na `/moje-allegro/zakupy/kupione`, paginacja `limit/offset`.
- **Równoległość**: profil znosi jedną przeglądarkę naraz — wywołania CLI są
  serializowane file-lockiem (czekają do 180 s). Nie odpalać `allegro` w tle
  równolegle.
- Struktura stron ustalona przez inspekcję 2026-07-12 — to nieoficjalny
  interfejs; przy zmianie frontu parser głośno zgłosi `ParseError`, a przy
  blokadzie `BlockedError` z instrukcją `allegro unblock`.

## Skill „zakupy"

`.claude/skills/zakupy/` — skill Claude Code do zakupów z listy (JSON `[{name, details}]`,
np. `example-list.json`). Dla każdej pozycji proponuje produkty (kupowane wcześniej +
najtańsze za jednostkę), generuje stronę na `http://localhost:8765` (wybór produktów
i ilości), a przycisk na stronie dodaje zaznaczone do koszyków na kontach — przez
`scripts/serve.py`, który dispatchuje po polu `shop` i woła CLI sklepu (obsługiwane:
`rossmann`, `allegro`). Dane robocze w `out/` (gitignore).

## Testy

Suite jest wyłącznie live — bije w prawdziwe serwisy z prawdziwymi kontami,
asercje na niezmiennikach (struktura, sortowanie), testy koszyków po sobie
sprzątają:

```bash
uv run pytest                          # wszystko (rossmann + allegro)
uv run pytest tests/test_allegro_*.py  # tylko allegro (wolniejsze: przeglądarka)
```
