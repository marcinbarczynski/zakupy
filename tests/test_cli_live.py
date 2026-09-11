"""Scenariusz 4: kontrakt CLI — stabilny JSON, kody wyjścia, brak sekretów w wyjściu."""

from __future__ import annotations

import json
import subprocess
import sys

from rossmann import auth

def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "rossmann.cli", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_search_json_contract():
    proc = run_cli("search", "szampon", "--limit", "3", "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) >= {"totalCount", "totalPages", "page", "products"}
    assert len(data["products"]) == 3
    for p in data["products"]:
        assert set(p) >= {"id", "name", "price", "pricePerUnit", "availability", "url"}


def test_cheapest_json_sorted_per_unit():
    """Ranking idzie rosnąco w obrębie jednostki bazowej.

    Cen z różnych baz (zł/l vs zł/szt.) nie da się porównywać między sobą, więc
    cheapest sortuje po (jednostka, wartość) — globalne sortowanie samych kwot
    nie jest kontraktem tej komendy.
    """
    proc = run_cli("cheapest", "mydło w płynie", "--per-unit", "--limit", "5", "--json")
    assert proc.returncode == 0, proc.stderr
    products = json.loads(proc.stdout)
    assert products
    pairs = [
        (p["pricePerUnitNormalized"]["unit"], p["pricePerUnitNormalized"]["value"])
        for p in products
    ]
    assert pairs == sorted(pairs)


def test_whoami_json_returns_account_email():
    proc = run_cli("whoami", "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["email"] == auth.Credentials.load().email


def test_missing_product_fails_with_clean_error():
    proc = run_cli("product", "999999999")
    assert proc.returncode == 1
    assert "błąd" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_password_never_leaks_to_output():
    password = auth.Credentials.load().password
    for args in (["login"], ["whoami", "--json"], ["search", "szampon", "--limit", "1", "--json"]):
        proc = run_cli(*args)
        assert password not in proc.stdout
        assert password not in proc.stderr
