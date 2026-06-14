"""FastAPI service.

The scaffold exposes only liveness/readiness; project/score/insight and the
Ask EngPulse endpoints arrive with their respective modules.
"""

from __future__ import annotations

from fastapi import FastAPI

from engpulse import __version__
from engpulse.api.routes import ask, projects
from engpulse.config import get_settings

app = FastAPI(title="EngPulse AI", version=__version__)
app.include_router(projects.router)
app.include_router(ask.router)


@app.get("/health")
def health() -> dict:
    """Liveness probe — does not touch external services."""

    return {"status": "ok", "version": __version__, "app_env": get_settings().app_env}


@app.get("/readiness")
def readiness() -> dict:
    """Readiness probe — verifies the database connection."""

    from sqlalchemy import text

    from engpulse.db.base import get_engine

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # pragma: no cover - depends on live DB
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


@app.get("/metrics")
def metrics() -> dict:
    """Placeholder metrics endpoint (Prometheus/Langfuse wiring lands later)."""

    return {"app": "engpulse", "version": __version__}
