"""CLI: `allegro <komenda>`. Każda komenda ma --json ze stabilnym formatem pod automatyzację."""

from __future__ import annotations

import json
import sys

import click

from . import auth, listing
from .browser import AllegroError, open_page
from .models import Offer


def _fail(message: str) -> None:
    click.echo(f"błąd: {message}", err=True)
    sys.exit(1)


def _print_offers(offers: list[Offer]) -> None:
    if not offers:
        click.echo("(brak wyników)")
        return
    for o in offers:
        price = f"{o.price:.2f} zł" if o.price is not None else "?"
        effective = o.effective_price()
        with_delivery = (
            " (Smart: dostawa 0 zł)"
            if o.smart or o.free_delivery
            else (f" ({effective:.2f} zł z dostawą)" if effective is not None and effective != o.price else "")
        )
        unit_price = o.effective_unit_price()
        per_unit = f"  {unit_price['value']:.2f} zł/{unit_price['unit']}" if unit_price else ""
        seller = f"  @{o.seller_login}" if o.seller_login else ""
        seller += f" ({o.seller_rating:.1f}%)" if o.seller_rating is not None else ""
        extras = "".join(
            [
                " [SPONSOROWANE]" if o.sponsored else "",
                f" [{o.product_offers_count} ofert]" if (o.product_offers_count or 0) > 1 else "",
            ]
        )
        click.echo(f"{o.offer_id:>12}  {price:>10}{with_delivery}{per_unit}{seller}{extras}  {o.title}")


@click.group()
def main() -> None:
    """Nieoficjalny interfejs do allegro.pl (steruje przeglądarką)."""


@main.command()
@click.argument("query")
@click.option("--sort", type=click.Choice(sorted(listing.SORT_MAP)), default="relevance")
@click.option("--min-price", type=float)
@click.option("--max-price", type=float)
@click.option("--page", "page_num", type=int, default=1)
@click.option("--limit", type=int, default=20, help="Maks. liczba zwróconych ofert")
@click.option("--json", "as_json", is_flag=True)
def search(query, sort, min_price, max_price, page_num, limit, as_json) -> None:
    """Wyszukaj oferty."""
    with open_page() as page:
        result = listing.search(
            page, query, sort=sort, price_from=min_price, price_to=max_price, page_num=page_num
        )
    result.offers = result.offers[:limit]
    if as_json:
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_offers(result.offers)
        click.echo(f"-- {result.total_count} wyników, strona {result.page}/{result.last_page}")


@main.command()
@click.argument("product_id")
@click.option("--sort", type=click.Choice(sorted(listing.SORT_MAP)), default="price")
@click.option("--limit", type=int, default=20)
@click.option("--json", "as_json", is_flag=True)
def offers(product_id, sort, limit, as_json) -> None:
    """Wszystkie oferty jednego produktu (mechanika "zobacz N ofert")."""
    with open_page() as page:
        result = listing.product_offers(page, product_id, sort=sort)
    result.offers = result.offers[:limit]
    if as_json:
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_offers(result.offers)


@main.command()
@click.argument("query")
@click.option("--per-unit/--no-per-unit", default=True, help="Ranking po cenie za jednostkę")
@click.option(
    "--smart/--no-smart",
    "smart_mode",
    default=True,
    help="Oferty Smart bez kosztu dostawy (konto ma Smart, koszyk przekroczy 49,90 zł)",
)
@click.option("--limit", type=int, default=10)
@click.option("--scan-pages", type=int, default=2)
@click.option("--json", "as_json", is_flag=True)
def cheapest(query, per_unit, smart_mode, limit, scan_pages, as_json) -> None:
    """Najtańsze oferty dla frazy — po efektywnej cenie jednostkowej."""
    with open_page() as page:
        result = listing.cheapest(
            page, query, per_unit=per_unit, smart_mode=smart_mode, limit=limit, scan_pages=scan_pages
        )
    if as_json:
        click.echo(json.dumps([o.to_dict() for o in result], ensure_ascii=False, indent=2))
    else:
        _print_offers(result)


@main.command()
@click.option("--headful", is_flag=True, help="Widoczne okno (konieczne przy captcha/2FA)")
def login(headful) -> None:
    """Zaloguj się danymi z pliku .allegro (sesja zostaje w profilu przeglądarki)."""
    credentials = auth.Credentials.load()
    with open_page(headful=headful) as page:
        auth.login(page, credentials, headful=headful)
        user = auth.whoami(page)
    click.echo(f"Zalogowano: {user.get('login') or user.get('email') or 'OK'}")


@main.command()
@click.option("--json", "as_json", is_flag=True)
def whoami(as_json) -> None:
    """Dane zalogowanego konta."""
    with open_page() as page:
        user = auth.whoami(page)
    if as_json:
        click.echo(json.dumps(user, ensure_ascii=False, indent=2))
    else:
        for key in ("login", "email"):
            if user.get(key):
                click.echo(f"{key}: {user[key]}")


@main.command()
def unblock() -> None:
    """Otwórz okno przeglądarki, żeby ręcznie rozwiązać captchę DataDome."""
    from .browser import BASE_URL

    with open_page(headful=True) as page:
        page.goto(BASE_URL + "/", wait_until="domcontentloaded")
        click.echo("Rozwiąż captchę / sprawdź stronę w oknie; Enter zamyka przeglądarkę…")
        input()


@main.group()
def basket() -> None:
    """Koszyk na koncie allegro.pl."""


@basket.command("show")
@click.option("--json", "as_json", is_flag=True)
def basket_show(as_json) -> None:
    """Zawartość koszyka."""
    from . import basket as basket_api

    with open_page() as page:
        data = basket_api.show(page)
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    items = data.get("items") or []
    if not items:
        click.echo("(koszyk pusty)")
        return
    for i in items:
        unit = f"{i['unitPrice']:.2f} zł" if i.get("unitPrice") is not None else "?"
        click.echo(f"{i.get('offerId'):>12}  {i.get('quantity')} szt. x {unit}  @{i.get('seller')}  {i.get('title')}")
    total = data.get("totalPrice")
    click.echo(f"-- razem: {total:.2f} zł" if total is not None else "-- razem: ?")


@basket.command("add")
@click.argument("offer_id")
@click.option("--qty", type=int, default=1)
def basket_add(offer_id, qty) -> None:
    """Dodaj ofertę do koszyka po jej ID."""
    from . import basket as basket_api

    with open_page() as page:
        title = basket_api.add(page, offer_id, quantity=qty)
    click.echo(f"Dodano do koszyka: {title} ({qty} szt.)")


@basket.command("remove")
@click.argument("offer_id")
def basket_remove(offer_id) -> None:
    """Usuń ofertę z koszyka."""
    from . import basket as basket_api

    with open_page() as page:
        basket_api.remove(page, offer_id)
    click.echo("Usunięto.")


@basket.command("clear")
def basket_clear() -> None:
    """Opróżnij koszyk."""
    from . import basket as basket_api

    with open_page() as page:
        n = basket_api.clear(page)
    click.echo(f"Usunięto pozycji: {n}")


@main.group()
def orders() -> None:
    """Historia zakupów na koncie allegro.pl."""


@orders.command("list")
@click.option("--limit", type=int, default=20)
@click.option("--json", "as_json", is_flag=True)
def orders_list(limit, as_json) -> None:
    """Lista zamówień od najnowszego."""
    from . import orders as orders_api

    with open_page() as page:
        result = orders_api.list_orders(page, limit=limit)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not result:
        click.echo("(brak zamówień)")
        return
    for o in result:
        date = (o.get("date") or "")[:10]
        total = f"{o['totalPrice']:.2f} zł" if o.get("totalPrice") is not None else "?"
        click.echo(f"{date}  {total:>10}  {len(o.get('items') or []):>3} poz.  @{o.get('seller')}")


@orders.command("products")
@click.option("--max-orders", type=int, default=50, help="Ile ostatnich zamówień zagregować")
@click.option("--json", "as_json", is_flag=True)
def orders_products(max_orders, as_json) -> None:
    """Agregat kupionych produktów: ile razy, ile sztuk, kiedy ostatnio."""
    from . import orders as orders_api

    with open_page() as page:
        result = orders_api.purchased_products(page, max_orders=max_orders)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for e in result:
        last = (e.get("lastOrderDate") or "")[:10]
        click.echo(f"{e.get('offerId'):>12}  x{e['timesBought']:<3} ost. {last}  {e.get('title')}")


def run() -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError:
        PlaywrightError = ()  # type: ignore[assignment]
    try:
        main(standalone_mode=True)
    except AllegroError as e:
        _fail(str(e))
    except PlaywrightError as e:
        _fail(f"przeglądarka: {str(e).splitlines()[0]}")


if __name__ == "__main__":
    run()
