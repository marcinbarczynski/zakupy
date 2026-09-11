"""Kontrakt CLI `allegro` odpalanego jak przez użytkownika (subprocess).

Każde wywołanie podnosi przeglądarkę, więc testów jest kilka szerokich.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent


def _run(*args: str, timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "allegro.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=timeout,
    )


def test_search_json_contract():
    proc = _run("search", "domestos zagęszczony", "--limit", "5", "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) >= {"totalCount", "page", "offers"}
    assert data["offers"]
    offer = data["offers"][0]
    expected_keys = {
        "shop",
        "offerId",
        "title",
        "price",
        "priceWithDelivery",
        "smart",
        "pricePerUnitNormalized",
        "effectivePrice",
        "effectiveUnitPrice",
        "seller",
        "sponsored",
        "url",
    }
    assert expected_keys <= set(offer)
    assert offer["shop"] == "allegro"


def test_bad_product_id_fails_cleanly():
    proc = _run("offers", "nie-ma-takiego-produktu-000")
    assert proc.returncode == 1
    assert "błąd:" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_password_never_leaks():
    from allegro.auth import Credentials

    password = Credentials.load().password
    for args in (("whoami", "--json"), ("search", "mydło", "--limit", "3")):
        proc = _run(*args)
        assert password not in proc.stdout
        assert password not in proc.stderr
