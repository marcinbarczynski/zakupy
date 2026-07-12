# rossmann — nieoficjalny interfejs CLI do sklepu rossmann.pl

Interfejs do wyszukiwania produktów, sprawdzania cen i operowania na koszyku
konta rossmann.pl. Pomyślany jako fundament pod skilla do robienia list
zakupów (konkretne produkty albo najtańsze z kategorii).

## Wymagania

- [uv](https://docs.astral.sh/uv/)
- plik `.rossmann` w korzeniu projektu (nie commitować!):

```
EMAIL=twoj@email.pl
PASSWORD=twoje-haslo
```

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

## Skill „zakupy"

`.claude/skills/zakupy/` — skill Claude Code do zakupów z listy (JSON `[{name, details}]`,
np. `example-list.json`). Dla każdej pozycji proponuje produkty (kupowane wcześniej +
najtańsze za jednostkę), generuje stronę na `http://localhost:8765` (wybór produktów
i ilości), a przycisk na stronie dodaje zaznaczone do koszyka na koncie — przez
`scripts/serve.py`, który dispatchuje po polu `shop` i woła CLI sklepu (gotowe na
kolejne sklepy). Dane robocze w `out/` (gitignore).

## Testy

Suite jest wyłącznie live — bije w prawdziwe API z prawdziwym kontem,
asercje na niezmiennikach (struktura, sortowanie), test koszyka po sobie sprząta:

```bash
uv run pytest
```
