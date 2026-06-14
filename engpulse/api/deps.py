"""FastAPI dependencies: DB session + helpers.

``get_session`` is overridden in tests to point at the ephemeral corpus DB, so
the whole API is exercised offline with no Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy.orm import Session

from engpulse.db.base import get_session_factory


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def parse_as_of(as_of: str | None) -> datetime | None:
    if not as_of:
        return None
    return datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc)
