"""Delivery & Deadline-Drift Analyzer (Module D).

Deterministic delivery-health signals over issues and their transition history:
cycle time, stale issues, deadline drift (due-date moves), re-estimation, and the
accountability gap of an issue marked Done with no merged PR. Findings are
grounded in issue keys and the transition records. No LLM.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from engpulse.db.models import Issue, PullRequest
from engpulse.metrics.thresholds import Thresholds, load_thresholds
from engpulse.metrics.types import Severity, days_between

_SEVERITY = {
    "stale_issue": Severity.MEDIUM,
    "deadline_drift": Severity.HIGH,
    "re_estimation": Severity.LOW,
    "done_without_merged_pr": Severity.HIGH,
}

_DONE_TYPES = {"completed", "canceled"}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


class IssueMetrics(BaseModel):
    key: str
    status: str | None = None
    status_type: str | None = None
    assignee: str | None = None
    estimate: float | None = None
    cycle_time_days: float | None = None
    age_days: float | None = None
    due_moves: int = 0
    reestimations: int = 0
    flags: list[str] = Field(default_factory=list)


class DeliveryFlag(BaseModel):
    type: str
    severity: str
    issue: str
    evidence: dict = Field(default_factory=dict)


class DeliveryReport(BaseModel):
    scope: str
    as_of: datetime
    issues: list[IssueMetrics] = Field(default_factory=list)
    flags: list[DeliveryFlag] = Field(default_factory=list)
    wip_by_assignee: dict[str, int] = Field(default_factory=dict)

    def flagged_issues(self, flag_type: str) -> set[str]:
        return {f.issue for f in self.flags if f.type == flag_type}


def _due_moves(issue: Issue) -> list[dict]:
    return [
        t for t in (issue.transitions or [])
        if t.get("from_due_date") or t.get("to_due_date")
    ]


def _completion_time(issue: Issue) -> datetime | None:
    """When the issue entered its current (done) state."""

    for t in reversed(issue.transitions or []):
        if t.get("to_state") == issue.status:
            return _parse(t.get("at"))
    return issue.source_updated_at


def compute_delivery(
    session: Session,
    team_key: str | None = None,
    thresholds: Thresholds | None = None,
    as_of: datetime | None = None,
) -> DeliveryReport:
    thresholds = thresholds or load_thresholds()
    cfg = thresholds.delivery
    as_of = as_of or datetime.now(timezone.utc)

    stmt = select(Issue).options(selectinload(Issue.assignee)).order_by(Issue.key)
    if team_key:
        stmt = stmt.where(Issue.team_key == team_key)
    issues = session.scalars(stmt).all()

    # Which issues have at least one merged PR linked to them.
    merged_issue_ids = set(
        session.scalars(
            select(PullRequest.linked_issue_id).where(
                PullRequest.linked_issue_id.is_not(None),
                PullRequest.merged_at.is_not(None),
            )
        ).all()
    )

    report = DeliveryReport(scope=team_key or "all", as_of=as_of)
    wip: Counter[str] = Counter()

    for issue in issues:
        is_done = (issue.status_type or "").lower() in _DONE_TYPES
        assignee = (
            issue.assignee.github_login or issue.assignee.name
            if issue.assignee else None
        )
        due_moves = _due_moves(issue)
        reestimations = len(issue.estimate_history or [])
        cycle = (
            days_between(issue.source_created_at, _completion_time(issue))
            if is_done else None
        )
        age = days_between(issue.source_updated_at, as_of)

        flags: list[str] = []
        if not is_done and age is not None and age > cfg.stale_issue_days:
            flags.append("stale_issue")
        if len(due_moves) >= cfg.deadline_drift_min_moves:
            flags.append("deadline_drift")
        if reestimations >= cfg.reestimation_min_changes:
            flags.append("re_estimation")
        if is_done and issue.id not in merged_issue_ids:
            flags.append("done_without_merged_pr")

        if not is_done and (issue.status_type or "").lower() == "started":
            if assignee:
                wip[assignee] += 1

        report.issues.append(IssueMetrics(
            key=issue.key, status=issue.status, status_type=issue.status_type,
            assignee=assignee, estimate=issue.estimate,
            cycle_time_days=cycle, age_days=age,
            due_moves=len(due_moves), reestimations=reestimations, flags=flags,
        ))
        for flag_type in flags:
            evidence = {"issue": issue.key}
            if flag_type == "deadline_drift":
                evidence["moves"] = len(due_moves)
                evidence["original_due"] = (
                    issue.original_due_date.date().isoformat()
                    if issue.original_due_date else None
                )
                evidence["current_due"] = (
                    issue.current_due_date.date().isoformat()
                    if issue.current_due_date else None
                )
            report.flags.append(DeliveryFlag(
                type=flag_type, severity=_SEVERITY[flag_type].value,
                issue=issue.key, evidence=evidence,
            ))

    report.wip_by_assignee = dict(wip)
    return report
