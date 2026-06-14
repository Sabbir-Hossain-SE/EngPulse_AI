"""Shared metric primitives: severity, evidence, and tz-safe time math."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def as_aware(dt: datetime | None) -> datetime | None:
    """Coerce to UTC-aware so Postgres (aware) and SQLite (naive) both work."""

    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def hours_between(start: datetime | None, end: datetime | None) -> float | None:
    start, end = as_aware(start), as_aware(end)
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600.0, 2)


def days_between(start: datetime | None, end: datetime | None) -> float | None:
    hours = hours_between(start, end)
    return None if hours is None else round(hours / 24.0, 2)
