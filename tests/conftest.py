"""Shared test fixtures.

Tests run fully offline: GitHub is served from recorded JSON, and the database
tests build the schema on in-memory SQLite (the models use portable types, so
the same metadata creates cleanly on both SQLite and Postgres).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from engpulse.db.base import Base
from engpulse.db import models  # noqa: F401  (register models on Base.metadata)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
