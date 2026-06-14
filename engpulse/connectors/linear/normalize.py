"""Pure DTO → ORM normalization for Linear issues.

Derives the deterministic facts later modules depend on — re-estimation history
and deadline drift (original vs current due date) — straight from the issue's
transition history. No DB, no network; fully unit-testable.
"""

from __future__ import annotations

from datetime import datetime

from engpulse.connectors.linear.schemas import LinearIssueDTO
from engpulse.db.models import Issue, Person


def to_person_from_assignee(dto: LinearIssueDTO) -> Person | None:
    if not dto.assignee_id and not dto.assignee_email:
        return None
    return Person(
        tracker_id=dto.assignee_id,
        email=dto.assignee_email,
        name=dto.assignee_name,
    )


def estimate_history(dto: LinearIssueDTO) -> list[dict]:
    """Estimate changes over time (drives the re-estimation / scope-creep signal)."""

    changes = []
    for t in dto.transitions:
        if t.from_estimate is not None or t.to_estimate is not None:
            if t.from_estimate != t.to_estimate:
                changes.append(
                    {
                        "at": t.at.isoformat() if t.at else None,
                        "from": t.from_estimate,
                        "to": t.to_estimate,
                    }
                )
    return changes


def _due_date_changes(dto: LinearIssueDTO):
    return [t for t in dto.transitions if t.from_due_date or t.to_due_date]


def original_due_date(dto: LinearIssueDTO) -> datetime | None:
    """The earliest known due date — the baseline drift is measured against."""

    changes = _due_date_changes(dto)
    if changes and changes[0].from_due_date is not None:
        return changes[0].from_due_date
    return dto.due_date


def to_issue(dto: LinearIssueDTO, assignee_id: int | None = None) -> Issue:
    return Issue(
        external_id=dto.id,
        key=dto.identifier,
        title=dto.title,
        project=dto.project_name or dto.team_key,
        team_key=dto.team_key,
        assignee_id=assignee_id,
        status=dto.status,
        status_type=dto.status_type,
        estimate=dto.estimate,
        estimate_history=estimate_history(dto),
        original_due_date=original_due_date(dto),
        current_due_date=dto.due_date,
        transitions=[t.serializable() for t in dto.transitions],
        labels=dto.labels,
        source_created_at=dto.created_at,
        source_updated_at=dto.updated_at,
    )
