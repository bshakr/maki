"""Shared DB fixtures.

Tests run against a DEDICATED ``<db>_test`` database, created on demand, never the dev
database named in ``DATABASE_URL``. This isolates the suite from any running maki instance —
notably the dev server's live deploy-events ingester, which commits real rows into the dev DB.
Without this, externally-committed rows leak into tests that assume an empty table.

Requires a live local Postgres (``docker compose up -d maki-postgres``). Does NOT skip when the
DB is absent: a missing DB is a real coverage gap and should fail loudly.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Point the config loader at the test fixture before importing anything under ``maki``. Settings
# loads the config lazily, but setting it here keeps any import order safe. Real runs use
# MAKI_CONFIG / the default path; the suite uses neutral-but-historical values that keep
# settings-reading tests stable.
os.environ.setdefault(
    "MAKI_CONFIG", str(Path(__file__).parent / "fixtures" / "maki.config.test.yaml")
)
# TrustedHostMiddleware rejects unknown Host headers; the TestClient sends "testserver". Allow it
# for the suite only (real runs never set this), so route tests keep their bare TestClient(app).
os.environ.setdefault("MAKI_ALLOWED_HOSTS", "testserver")

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from maki.db.models import Base
from maki.settings import settings


def _test_database_url():
    """Derive a sibling ``<db>_test`` URL from DATABASE_URL, creating the database if needed."""
    url = make_url(settings.database_url)
    test_db = f"{url.database}_test"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": test_db}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    admin.dispose()
    return url.set(database=test_db)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(_test_database_url(), future=True)
    # Build the schema from the models (carries the NULLS NOT DISTINCT unique constraint); keeps
    # the suite self-contained and independent of alembic migration state on the dev DB.
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    """A session bound to a connection-level transaction rolled back at teardown.

    The test runs inside an outer transaction that is never committed, so the database is left
    untouched even though the repository/ingester call ``session.commit()`` internally (savepoints
    keep per-service failure isolation working).
    """
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    db = factory()
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def session_factory(session):
    """A ``session_factory`` matching ``engine.get_session``: a contextmanager yielding ``session``.

    Store-backed services (history/activity) take a ``session_factory``; wiring them to the single
    test-scoped session makes seeded rows visible to assertions and rolled back at teardown.
    """

    @contextmanager
    def factory():
        yield session

    return factory
