"""CLI: `rossmann <komenda>`. Każda komenda ma --json ze stabilnym formatem pod automatyzację."""

from __future__ import annotations

import json
import sys

import click
import httpx

from . import auth, basket as basket_api, catalog, orders as orders_api
from .http import RossmannError, make_client
from .models import Category, Product

_SORT_MAP = {
    "default": "default",
    "price": "priceAsc",
    "price-desc": "priceDesc",
    "newest": "newestFirst",
}


def _fail(message: str) -> None:
    click.echo(f"błąd: {message}", err=True)
    sys.exit(1)


def _print_products(products: list[Product]) -> None:
    if not products:
        click.echo("(brak wyników)")
        return
    for p in products:
        price = f"{p.price:.2f} zł" if p.price is not None else "?"
        promo = f" [{p.promotion}]" if p.promotion else ""
        per_unit = f" ({p.price_per_unit})" if p.price_per_unit else ""
        avail = "" if p.availability == "available" else f" !{p.availability}"
        click.echo(f"{p.id:>8}  {price:>10}{per_unit}{promo}{avail}  {p.name}")


@click.group()
def main() -> None:
    """Nieoficjalny interfejs do sklepu rossmann.pl."""


@main.command()
@click.argument("query")
@click.option("--category", type=int, help="ID kategorii (patrz: rossmann categories)")
@click.option("--min-price", type=float)
@click.option("--max-price", type=float)
@click.option("--sort", type=click.Choice(sorted(_SORT_MAP)), default="default")
@click.option("--page", type=int, default=1)
@click.option("--limit", type=int, default=24, help="Maks. liczba zwróconych produktów")
@click.option("--json", "as_json", is_flag=True)
def search(query, category, min_price, max_price, sort, page, limit, as_json) -> None:
    """Wyszukaj produkty."""
    with make_client() as client:
        result = catalog.search(
            client,
            query=query,
            category_id=category,
            page=page,
            order=_SORT_MAP[sort],
            price_from=min_price,
            price_to=max_price,
        )
    result.products = result.products[:limit]
    if as_json:
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_products(result.products)
        click.echo(f"-- {result.total_count} wyników, strona {result.page}/{result.total_pages}")


@main.command()
@click.option("--tree", is_flag=True, help="Pełne drzewo zamiast tylko głównych kategorii")
@click.option("--json", "as_json", is_flag=True)
def categories(tree, as_json) -> None:
    """Drzewo kategorii sklepu."""
    with make_client() as client:
        cats = catalog.categories(client)
    if as_json:
        click.echo(json.dumps([c.to_dict() for c in cats], ensure_ascii=False, indent=2))
        return

    def _print(cs: list[Category], indent: int = 0) -> None:
        for c in cs:
            count = f" ({c.products_count})" if c.products_count is not None else ""
            click.echo(f"{'  ' * indent}{c.id:>6}  {c.name}{count}")
            if tree:
                _print(c.children, indent + 1)

    _print(cats)


@main.command()
@click.argument("product_id", type=int)
@click.option("--json", "as_json", is_flag=True)
def product(product_id, as_json) -> None:
    """Szczegóły produktu po jego ID."""
    with make_client() as client:
        p = catalog.product_details(client, product_id)
    if as_json:
        click.echo(json.dumps(p.to_dict(), ensure_ascii=False, indent=2))
        return
    for k, v in p.to_dict().items():
        if v is not None:
            click.echo(f"{k}: {v}")


@main.command()
@click.argument("query")
@click.option("--category", type=int, help="ID kategorii zamiast/oprócz frazy")
@click.option("--per-unit", is_flag=True, help="Sortuj po cenie za jednostkę (np. za 100 ml)")
@click.option("--include-unavailable", is_flag=True)
@click.option("--limit", type=int, default=10)
@click.option("--json", "as_json", is_flag=True)
def cheapest(query, category, per_unit, include_unavailable, limit, as_json) -> None:
    """Najtańsze produkty dla frazy lub kategorii."""
    with make_client() as client:
        products = catalog.cheapest(
            client,
            query=query or None,
            category_id=category,
            per_unit=per_unit,
            available_only=not include_unavailable,
            limit=limit,
        )
    if as_json:
        click.echo(json.dumps([p.to_dict() for p in products], ensure_ascii=False, indent=2))
    else:
        _print_products(products)


@main.command()
def login() -> None:
    """Zaloguj się danymi z pliku .rossmann i zapisz token."""
    token = auth.login()
    user = auth.whoami(token)
    click.echo(f"Zalogowano: {user.get('email') or user.get('Email') or 'OK'}")


@main.command()
@click.option("--json", "as_json", is_flag=True)
def whoami(as_json) -> None:
    """Dane zalogowanego użytkownika."""
    user = auth.whoami(auth.get_token())
    if as_json:
        click.echo(json.dumps(user, ensure_ascii=False, indent=2))
    else:
        for key in ("email", "Email", "nick", "Nick", "name", "firstName", "lastName"):
            if user.get(key):
                click.echo(f"{key}: {user[key]}")


@main.group()
def orders() -> None:
    """Historia zamówień na koncie rossmann.pl."""


@orders.command("list")
@click.option("--limit", type=int, default=20)
@click.option("--json", "as_json", is_flag=True)
def orders_list(limit, as_json) -> None:
    """Lista zamówień od najnowszego."""
    with make_client(token=auth.get_token()) as client:
        result = orders_api.list_orders(client, limit=limit)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not result:
        click.echo("(brak zamówień)")
        return
    for o in result:
        date = (o.get("orderDate") or "")[:10]
        items = len(o.get("productsInfosHistory") or []) + (o.get("otherItems") or 0)
        click.echo(
            f"{o.get('orderId'):>10}  {date}  {o.get('price'):>8.2f} zł"
            f"  {items:>3} poz.  {o.get('status')}"
        )


@orders.command("show")
@click.argument("order_id", type=int)
@click.option("--json", "as_json", is_flag=True)
def orders_show(order_id, as_json) -> None:
    """Szczegóły zamówienia online (pełna lista produktów)."""
    with make_client(token=auth.get_token()) as client:
        details = orders_api.order_details(client, order_id)
    if as_json:
        click.echo(json.dumps(details, ensure_ascii=False, indent=2))
        return
    for p in (details.get("productsSummary") or {}).get("products") or []:
        name = " ".join(filter(None, [p.get("brand"), (p.get("name") or "").strip(), p.get("caption")]))
        click.echo(f"{p.get('id'):>8}  {p.get('quantity')} szt. x {p.get('unitPrice'):>7.2f} zł  {name} ({p.get('unit')})")


@orders.command("products")
@click.option("--max-orders", type=int, default=50, help="Ile ostatnich zamówień zagregować")
@click.option("--json", "as_json", is_flag=True)
def orders_products(max_orders, as_json) -> None:
    """Agregat kupionych produktów: ile razy, ile sztuk, kiedy ostatnio."""
    with make_client(token=auth.get_token()) as client:
        result = orders_api.purchased_products(client, max_orders=max_orders)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for e in result:
        name = " ".join(filter(None, [e.get("brand"), e.get("name"), e.get("caption")]))
        last = (e.get("lastOrderDate") or "")[:10]
        click.echo(f"{e['id']:>8}  x{e['timesBought']:<3} ost. {last}  {name} ({e.get('unit')})")


@main.group()
def basket() -> None:
    """Koszyk na koncie rossmann.pl."""


@basket.command("show")
@click.option("--json", "as_json", is_flag=True)
def basket_show(as_json) -> None:
    """Zawartość koszyka."""
    with make_client(token=auth.get_token()) as client:
        data = basket_api.show(client)
    items = data.get("cartItems") or []
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not items:
        click.echo("(koszyk pusty)")
        return
    for i in items:
        name = " ".join(filter(None, [i.get("brand"), (i.get("name") or "").strip()]))
        click.echo(f"{i.get('id'):>8}  {i.get('quantity')} szt.  {name} ({i.get('unit')})")
    click.echo(f"-- razem: {data.get('totalPrice')} zł, {data.get('totalProductQuantity')} szt.")


@basket.command("add")
@click.argument("product_id", type=int)
@click.option("--qty", type=int, default=1)
def basket_add(product_id, qty) -> None:
    """Dodaj produkt do koszyka po jego ID."""
    token = auth.get_token()
    with make_client(token=token) as client:
        product = catalog.product_details(client, product_id)
        message = basket_api.add(client, product.raw, quantity=qty)
    click.echo(f"{message} ({product.name}, {qty} szt.)")


@basket.command("remove")
@click.argument("product_id", type=int)
def basket_remove(product_id) -> None:
    """Usuń produkt z koszyka."""
    with make_client(token=auth.get_token()) as client:
        basket_api.remove(client, product_id)
    click.echo("Usunięto.")


@basket.command("clear")
def basket_clear() -> None:
    """Opróżnij koszyk."""
    with make_client(token=auth.get_token()) as client:
        n = basket_api.clear(client)
    click.echo(f"Usunięto pozycji: {n}")


def run() -> None:
    try:
        main(standalone_mode=True)
    except RossmannError as e:
        _fail(str(e))
    except httpx.HTTPError as e:
        _fail(f"HTTP: {e}")


if __name__ == "__main__":
    run()
