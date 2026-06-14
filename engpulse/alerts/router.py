"""Alert router (Module K).

Turns detector flags into severity-classified, role-routed alerts; de-duplicates
(one alert per subject+type, merging the contributing reasons) and suppresses
anything below the configured minimum severity — so a lead gets a short,
evidence-bearing list rather than a flood.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from engpulse.alerts.config import AlertConfig, load_alert_config, severity_rank
from engpulse.metrics import (
    compute_ci_health,
    compute_delivery,
    compute_knowledge_risk,
    compute_pr_flow,
)
from engpulse.scoring import ProjectScore, compute_project_score

# detector flag → alert type
_PR_TYPE = {
    "abandoned": "execution", "stale": "execution", "unreviewed": "execution",
    "oversized": "review_bottleneck", "merged_without_review": "review_bottleneck",
    "review_bottleneck": "review_bottleneck",
}
_DELIVERY_TYPE = {
    "stale_issue": "delivery_risk", "deadline_drift": "delivery_risk",
    "re_estimation": "delivery_risk", "done_without_merged_pr": "execution",
}


class Alert(BaseModel):
    type: str
    severity: str
    roles: list[str] = Field(default_factory=list)
    subject: str
    owner: str | None = None
    reasons: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    confidence: float = 0.95     # deterministic flags → high confidence
    evidence: dict = Field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return f"{self.type}:{self.subject}"


def _dedupe(alerts: list[Alert]) -> list[Alert]:
    by_key: dict[str, Alert] = {}
    for a in alerts:
        existing = by_key.get(a.dedup_key)
        if existing is None:
            by_key[a.dedup_key] = a
            continue
        existing.reasons = sorted(set(existing.reasons) | set(a.reasons))
        existing.evidence = {**existing.evidence, **a.evidence}
        if existing.owner is None:
            existing.owner = a.owner
        if severity_rank(a.severity) > severity_rank(existing.severity):
            existing.severity = a.severity
    return list(by_key.values())


def route_alerts(
    pr_report, delivery_report, ci_report, knowledge_report,
    score: ProjectScore | None = None, config: AlertConfig | None = None,
) -> list[Alert]:
    config = config or load_alert_config()
    raw: list[Alert] = []

    pr_authors = {m.number: m.author for m in pr_report.pull_requests}
    for f in pr_report.flags:
        atype = _PR_TYPE.get(f.type, "execution")
        subject = f"PR#{f.pr_number}" if f.pr_number else "review"
        raw.append(Alert(type=atype, severity=f.severity, subject=subject,
                         owner=pr_authors.get(f.pr_number), reasons=[f.type],
                         evidence=f.evidence))

    assignees = {i.key: i.assignee for i in delivery_report.issues}
    for f in delivery_report.flags:
        atype = _DELIVERY_TYPE.get(f.type, "delivery_risk")
        raw.append(Alert(type=atype, severity=f.severity, subject=f.issue,
                         owner=assignees.get(f.issue), reasons=[f.type],
                         evidence=f.evidence))

    for f in ci_report.flaky_tests:
        raw.append(Alert(type="ci_health", severity=config.flaky_alert_severity,
                         subject=f.test, reasons=["flaky_test"],
                         evidence={"flip_rate": f.flip_rate, "runs": f.evidence_run_ids}))

    for f in knowledge_report.flags:
        raw.append(Alert(type="knowledge_risk", severity=f.severity, subject=f.module,
                         owner=f.evidence.get("owner"), reasons=[f.type],
                         evidence=f.evidence))

    if score is not None and score.band in ("At Risk", "Critical"):
        raw.append(Alert(
            type="delivery_risk",
            severity="critical" if score.band == "Critical" else "high",
            subject="project", reasons=["health_score_drop"],
            evidence={"composite": score.composite, "band": score.band},
        ))

    # Assign roles + action, then dedupe and suppress.
    for a in raw:
        a.roles = config.roles_for(a.type)
        a.recommended_action = config.action_for(a.type)

    deduped = _dedupe(raw)
    floor = severity_rank(config.min_severity)
    kept = [a for a in deduped if severity_rank(a.severity) >= floor]
    kept.sort(key=lambda a: severity_rank(a.severity), reverse=True)
    return kept


def route_project(
    session: Session,
    repo_full_name: str,
    team_key: str | None = None,
    as_of: datetime | None = None,
    config: AlertConfig | None = None,
) -> tuple[list[Alert], ProjectScore]:
    """Compute all detector reports + score for a project and route the alerts."""

    pr = compute_pr_flow(session, repo_full_name, as_of=as_of)
    delivery = compute_delivery(session, team_key=team_key, as_of=as_of)
    ci = compute_ci_health(session, repo_full_name)
    knowledge = compute_knowledge_risk(session, repo_full_name)
    score = compute_project_score(session, repo_full_name, team_key=team_key, as_of=as_of)
    alerts = route_alerts(pr, delivery, ci, knowledge, score, config=config)
    return alerts, score
