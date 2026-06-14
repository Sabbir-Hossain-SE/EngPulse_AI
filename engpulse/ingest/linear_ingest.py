"""Linear ingestion orchestrator (sub-step 2.2).

Pulls issues (with assignees and transition history), upserts them idempotently,
and records a cursor + audit row for the ``issues`` resource. For live runs the
cursor's high-water mark is passed back to Linear as an ``updatedAt`` filter so
each run only fetches changed issues. ``dry_run`` fetches + counts without the DB.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from engpulse.connectors.linear.client import build_linear_client
from engpulse.connectors.linear.normalize import to_person_from_assignee
from engpulse.connectors.linear.schemas import LinearIssueDTO
from engpulse.db.base import session_scope
from engpulse.ingest.audit import advance_cursor, audit_run, get_or_create_cursor
from engpulse.ingest.upsert import upsert_issue, upsert_person_tracker
from engpulse.logging import get_logger

log = get_logger(__name__)
SOURCE = "linear"


@dataclass
class LinearIngestReport:
    scope: str
    issues: int = 0
    assignees: int = 0
    with_due_drift: int = 0
    with_reestimation: int = 0
    persisted: bool = False
    audits: list[dict] = field(default_factory=list)


def _max_dt(values: list[datetime | None]) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _persist(session: Session, scope: str, issues: list[LinearIssueDTO]) -> LinearIngestReport:
    report = LinearIngestReport(scope=scope, persisted=True)
    assignees: set[str] = set()
    with audit_run(session, SOURCE, "issues", scope) as counters:
        for dto in issues:
            counters.seen += 1
            assignee = upsert_person_tracker(
                session, dto.assignee_id, dto.assignee_name, dto.assignee_email
            )
            if assignee is not None:
                assignees.add(assignee.tracker_id or assignee.email)
            issue = upsert_issue(
                session, dto, assignee_id=assignee.id if assignee else None
            )
            counters.written += 1
            if issue.estimate_history:
                report.with_reestimation += 1
            if issue.original_due_date and issue.current_due_date and (
                issue.original_due_date != issue.current_due_date
            ):
                report.with_due_drift += 1
        report.issues = counters.written
    report.assignees = len(assignees)
    advance_cursor(session, SOURCE, "issues", scope,
                   _max_dt([i.updated_at for i in issues]))
    report.audits = _audit_summary(session, scope)
    return report


def _audit_summary(session: Session, scope: str) -> list[dict]:
    from sqlalchemy import select

    from engpulse.db.models import SyncAudit

    rows = session.scalars(
        select(SyncAudit).where(
            SyncAudit.source == SOURCE, SyncAudit.scope == scope
        ).order_by(SyncAudit.id)
    ).all()
    return [
        {"resource": r.resource, "seen": r.records_seen,
         "written": r.records_written, "status": r.status}
        for r in rows
    ]


def _summarize_only(scope: str, issues: list[LinearIssueDTO]) -> LinearIngestReport:
    from engpulse.connectors.linear.normalize import estimate_history, original_due_date

    drift = sum(
        1 for i in issues
        if original_due_date(i) and i.due_date and original_due_date(i) != i.due_date
    )
    reest = sum(1 for i in issues if estimate_history(i))
    assignees = {i.assignee_id or i.assignee_email for i in issues
                 if i.assignee_id or i.assignee_email}
    return LinearIngestReport(
        scope=scope,
        issues=len(issues),
        assignees=len(assignees),
        with_due_drift=drift,
        with_reestimation=reest,
        persisted=False,
    )


def ingest_linear(
    source: str = "fixture",
    team_key: str | None = None,
    limit: int = 200,
    since: datetime | None = None,
    dry_run: bool = False,
) -> LinearIngestReport:
    """Ingest Linear issues for a team (or all teams) end-to-end."""

    scope = f"linear:{team_key or 'all'}"
    client = build_linear_client(source)

    # Live incremental: resume from the stored high-water mark unless overridden.
    if since is None and source == "live":
        with session_scope() as session:
            cursor = get_or_create_cursor(session, SOURCE, "issues", scope)
            since = cursor.updated_since

    issues = asyncio.run(client.list_issues(team_key=team_key, since=since, limit=limit))
    log.info("Fetched %d Linear issue(s) for %s", len(issues), scope)

    if dry_run:
        return _summarize_only(scope, issues)

    with session_scope() as session:
        return _persist(session, scope, issues)
