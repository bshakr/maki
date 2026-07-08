"""Ingester-test fixtures. The ``engine``/``session`` fixtures live in the shared root
``tests/conftest.py`` (isolated ``<db>_test`` database); this adds the ``session_factory`` the
ingester needs."""

from contextlib import contextmanager

import pytest


@pytest.fixture
def session_factory(session):
    """A ``session_factory`` matching ``engine.get_session``: a contextmanager yielding ``session``.

    Every ``run_once()`` call reuses the single test-scoped session so its writes are visible to
    assertions and are rolled back at teardown. ``commit()`` inside the ingester is harmless here
    (the outer transaction is never committed; savepoints keep failure isolation working).
    """

    @contextmanager
    def factory():
        yield session

    return factory
