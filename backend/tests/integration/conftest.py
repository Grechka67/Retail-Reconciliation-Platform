"""Postgres-backed test fixtures.

These tests exercise real reconciliation / cash-close code paths, which open
their own sessions and commit. So we can't wrap a test in one rollback — we
truncate between tests instead. That is destructive, so the fixtures refuse
to run unless the target database is clearly a throwaway test DB.

Point DATABASE_URL at a *_test database (or set OT_ALLOW_TEST_DB=1) before
running these. CI provisions a dedicated postgres service for exactly this.
"""
import os

import pytest
from sqlmodel import SQLModel, text

import app.models  # noqa: F401  — registers every table on SQLModel.metadata
from app.db import engine


def _is_throwaway_db() -> bool:
    name = (engine.url.database or "")
    return name.endswith("_test") or os.getenv("OT_ALLOW_TEST_DB") == "1"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    if not _is_throwaway_db():
        pytest.skip(
            f"refusing to run destructive DB tests against {engine.url.database!r}; "
            "use a *_test database or set OT_ALLOW_TEST_DB=1"
        )
    SQLModel.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    """Empty every table before each test for isolation."""
    tables = ", ".join(t.name for t in SQLModel.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield
