"""Celery application.

Wired to Redis now so the worker container has something to run; real tasks
(scheduled incremental sync, webhook processing) arrive with the ingestion
milestone.
"""

from __future__ import annotations

from celery import Celery

from engpulse.config import get_settings

settings = get_settings()

celery_app = Celery(
    "engpulse",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(task_track_started=True, timezone="UTC")


@celery_app.task(name="engpulse.ping")
def ping() -> str:
    """Trivial health task to confirm the broker round-trips."""

    return "pong"
