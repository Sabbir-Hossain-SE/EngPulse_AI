"""Incremental-sync bookkeeping: cursors and the audit log.

Every connector run records what it saw vs wrote (``SyncAudit``) and advances a
high-water mark (``SyncCursor``) so the next run only fetches what changed. This
makes the ingestion layer auditable and re-runnable — a core PRD §8.A deliverable.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from engpulse.db.models import SyncAudit, SyncCursor
from engpulse.logging import get_logger

log = get_logger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    """Coerce to UTC-aware so comparisons work whether the backend stored the
    value tz-aware (Postgres) or naive (SQLite, used in tests)."""

    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def get_or_create_cursor(
    session: Session, source: str, resource: str, scope: str
) -> SyncCursor:
    cursor = session.scalars(
        select(SyncCursor).where(
            SyncCursor.source == source,
            SyncCursor.resource == resource,
            SyncCursor.scope == scope,
        )
    ).first()
    if cursor is None:
        cursor = SyncCursor(source=source, resource=resource, scope=scope)
        session.add(cursor)
        session.flush()
    return cursor


def advance_cursor(
    session: Session,
    source: str,
    resource: str,
    scope: str,
    high_water: datetime | None,
) -> None:
    cursor = get_or_create_cursor(session, source, resource, scope)
    cursor.last_run_at = utcnow()
    current = _as_aware(cursor.updated_since)
    incoming = _as_aware(high_water)
    if incoming is not None and (current is None or incoming > current):
        cursor.updated_since = high_water
    session.flush()


class _Counters:
    """Mutable seen/written tally yielded to an ``audit_run`` block."""

    def __init__(self) -> None:
        self.seen = 0
        self.written = 0


@contextmanager
def audit_run(
    session: Session, source: str, resource: str, scope: str
) -> Iterator[_Counters]:
    """Record one resource sync. Failures are captured (status='error') and
    re-raised so the caller decides whether one resource's failure aborts the run.
    """

    audit = SyncAudit(
        source=source,
        resource=resource,
        scope=scope,
        started_at=utcnow(),
        status="running",
    )
    session.add(audit)
    session.flush()
    counters = _Counters()
    try:
        yield counters
        audit.status = "ok"
    except Exception as exc:  # noqa: BLE001 - recorded then re-raised
        audit.status = "error"
        audit.error_message = str(exc)[:2000]
        log.warning("Sync of %s/%s for %s failed: %s", source, resource, scope, exc)
        raise
    finally:
        audit.records_seen = counters.seen
        audit.records_written = counters.written
        audit.finished_at = utcnow()
        session.flush()
