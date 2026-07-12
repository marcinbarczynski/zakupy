"""Fixtury wspólne. Cała suite bije w żywe API rossmann.pl — bez mocków."""

from __future__ import annotations

import pytest

from rossmann import auth
from rossmann.http import make_client


@pytest.fixture(scope="session")
def client():
    with make_client() as c:
        yield c


@pytest.fixture(scope="session")
def authed_client():
    """Jedno logowanie na całą sesję testową."""
    with make_client(token=auth.get_token()) as c:
        yield c
