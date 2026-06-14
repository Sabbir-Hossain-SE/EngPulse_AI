"""Composite project-health scoring (Module H).

Each sub-score starts at 100 and loses config-driven points per flag by severity;
the composite is their weighted average, mapped to a status band. Every score
decomposes to the contributing flags, so any number can be explained.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from engpulse.db.models import Repository, Score
from engpulse.metrics import (
    compute_ci_health,
    compute_delivery,
    compute_knowledge_risk,
    compute_pr_flow,
)
from engpulse.metrics.thresholds import Thresholds, load_thresholds
from engpulse.scoring.config import ScoringConfig, load_scoring_config


class SubScore(BaseModel):
    name: str
    score: float
    weight: float
    penalty: float
    flag_count: int
    contributors: list[str] = Field(default_factory=list)


class ProjectScore(BaseModel):
    project: str
    as_of: datetime
    composite: float
    band: str
    sub_scores: list[SubScore] = Field(default_factory=list)

    def as_breakdown(self) -> dict:
        return {s.name: s.score for s in self.sub_scores}


def _sub(name: str, penalty: float, weight: float, count: int, contributors) -> SubScore:
    return SubScore(
        name=name, score=max(0.0, 100.0 - penalty), weight=weight,
        penalty=penalty, flag_count=count, contributors=list(contributors),
    )


def compute_project_score(
    session: Session,
    repo_full_name: str,
    team_key: str | None = None,
    as_of: datetime | None = None,
    scoring: ScoringConfig | None = None,
    thresholds: Thresholds | None = None,
) -> ProjectScore:
    scoring = scoring or load_scoring_config()
    thresholds = thresholds or load_thresholds()
    as_of = as_of or datetime.now(timezone.utc)
    w = scoring.weights

    pr = compute_pr_flow(session, repo_full_name, thresholds, as_of)
    delivery = compute_delivery(session, team_key, thresholds, as_of)
    ci = compute_ci_health(session, repo_full_name, thresholds)
    knowledge = compute_knowledge_risk(session, repo_full_name, thresholds)

    rf_pen = sum(scoring.penalty(f.severity) for f in pr.flags)
    del_pen = sum(scoring.penalty(f.severity) for f in delivery.flags)
    ci_pen = (
        len(ci.flaky_tests) * scoring.penalty(scoring.flaky_severity)
        + sum(scoring.penalty(scoring.duration_regression_severity)
              for t in ci.duration_trends if t.regression)
    )
    kn_pen = sum(scoring.penalty(f.severity) for f in knowledge.flags)

    sub_scores = [
        _sub("review_flow", rf_pen, w.get("review_flow", 0),
             len(pr.flags), [f.type for f in pr.flags]),
        _sub("delivery", del_pen, w.get("delivery", 0),
             len(delivery.flags), [f"{f.issue}:{f.type}" for f in delivery.flags]),
        _sub("ci_test", ci_pen, w.get("ci_test", 0),
             len(ci.flaky_tests), [f"flaky:{t.test}" for t in ci.flaky_tests]),
        _sub("knowledge", kn_pen, w.get("knowledge", 0),
             len(knowledge.flags), [f.module for f in knowledge.flags]),
    ]

    total_w = sum(s.weight for s in sub_scores) or 1.0
    composite = round(sum(s.score * s.weight for s in sub_scores) / total_w, 2)
    return ProjectScore(
        project=repo_full_name, as_of=as_of, composite=composite,
        band=scoring.band_for(composite), sub_scores=sub_scores,
    )


def persist_project_score(session: Session, score: ProjectScore) -> Score | None:
    """Persist a Score row, computing the delta from the latest prior score."""

    repo = session.scalars(
        select(Repository).where(Repository.full_name == score.project)
    ).first()
    if repo is None:
        return None
    last = session.scalars(
        select(Score).where(Score.repo_id == repo.id).order_by(Score.id.desc())
    ).first()
    delta = round(score.composite - last.composite, 2) if last and last.composite else None
    row = Score(
        repo_id=repo.id, score_date=score.as_of, composite=score.composite,
        sub_scores=score.as_breakdown(), band=score.band, delta=delta,
    )
    session.add(row)
    session.flush()
    # Keep the repo's denormalized health fields in step.
    repo.health_score = score.composite
    repo.risk_band = score.band
    session.flush()
    return row
