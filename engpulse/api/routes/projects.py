"""Project, score, alert, digest, and knowledge endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from engpulse.alerts import build_digest, render_digest, route_project
from engpulse.api.deps import get_session, parse_as_of
from engpulse.db.models import Repository
from engpulse.metrics import compute_knowledge_risk
from engpulse.scoring import compute_project_score

router = APIRouter()


@router.get("/projects")
def list_projects(session: Session = Depends(get_session)) -> list[dict]:
    repos = session.scalars(select(Repository).order_by(Repository.full_name)).all()
    return [
        {"repo": r.full_name, "health_score": r.health_score, "band": r.risk_band}
        for r in repos
    ]


@router.get("/score")
def project_score(
    repo: str = Query(...),
    team: str | None = None,
    as_of: str | None = None,
    session: Session = Depends(get_session),
):
    return compute_project_score(session, repo, team_key=team, as_of=parse_as_of(as_of))


@router.get("/alerts")
def project_alerts(
    repo: str = Query(...),
    team: str | None = None,
    role: str | None = None,
    as_of: str | None = None,
    session: Session = Depends(get_session),
):
    alerts, score = route_project(session, repo, team_key=team, as_of=parse_as_of(as_of))
    if role:
        alerts = [a for a in alerts if role in a.roles]
    return {"project": score.project, "composite": score.composite,
            "band": score.band, "alerts": alerts}


@router.get("/digest")
def project_digest(
    repo: str = Query(...),
    team: str | None = None,
    role: str = "EM",
    period: str = "daily",
    as_of: str | None = None,
    session: Session = Depends(get_session),
):
    alerts, score = route_project(session, repo, team_key=team, as_of=parse_as_of(as_of))
    digest = build_digest(alerts, score, role=role, period=period)
    return {"markdown": render_digest(digest), "digest": digest}


@router.get("/knowledge")
def project_knowledge(
    repo: str = Query(...),
    session: Session = Depends(get_session),
):
    return compute_knowledge_risk(session, repo)
