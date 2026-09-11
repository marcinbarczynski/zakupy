"""Fixtury wspólne. Cała suite bije w żywe serwisy (rossmann.pl, allegro.pl) — bez mocków."""

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


# scope=module (nie session): profil znosi jedną przeglądarkę naraz, a testy CLI
# odpalają allegro w subprocessach — sesyjna przeglądarka blokowałaby im profil.
@pytest.fixture(scope="module")
def allegro_page():
    """Jedna przeglądarka na moduł testów allegro (profil trwały)."""
    from allegro.browser import open_page

    with open_page() as page:
        yield page


@pytest.fixture(scope="module")
def allegro_logged_page(allegro_page):
    """Zalogowana sesja allegro; bez ważnej sesji w profilu — skip z instrukcją."""
    from allegro import auth as allegro_auth

    if not allegro_auth.is_logged_in(allegro_page):
        try:
            allegro_auth.login(allegro_page)
        except allegro_auth.AuthError as e:
            pytest.skip(f"brak sesji allegro ({e}); uruchom: uv run allegro login --headful")
    return allegro_page
