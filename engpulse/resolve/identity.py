"""Cross-system identity merge.

A GitHub-sourced ``Person`` (login + user id) and a Linear-sourced ``Person``
(tracker id) are the same human; this collapses them into one record keyed by
email, repointing every foreign key so the linked graph stays intact.

The merge is deterministic and idempotent: once two records share one merged row,
a second pass groups a single person per email and does nothing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from engpulse.db.models import (
    Commit,
    Insight,
    Issue,
    Message,
    Person,
    PullRequest,
    pr_reviewers,
)

# Tables whose person FK must be repointed from a duplicate to the canonical row.
_FK_TARGETS = (
    (PullRequest, "author_id"),
    (Commit, "author_id"),
    (Issue, "assignee_id"),
    (Insight, "owner_id"),
    (Message, "author_id"),
)

# Identity fields copied onto the canonical row when it is missing them.
_IDENTITY_FIELDS = (
    "github_user_id", "github_login", "tracker_id", "email", "slack_id", "name",
)


@dataclass
class Merge:
    canonical_id: int
    merged_id: int
    method: str
    key: str


@dataclass
class IdentityResult:
    people_before: int = 0
    people_after: int = 0
    merges: list[Merge] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "people_before": self.people_before,
            "people_after": self.people_after,
            "merged": len(self.merges),
            "by_method": _count_by(self.merges),
        }


def _count_by(merges: list[Merge]) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in merges:
        out[m.method] = out.get(m.method, 0) + 1
    return out


def _norm_email(email: str | None) -> str | None:
    return email.strip().lower() if email else None


def _pick_canonical(group: list[Person]) -> Person:
    """Prefer the GitHub identity (primary source); break ties by lowest id."""

    github_rows = [p for p in group if p.github_user_id is not None]
    pool = github_rows or group
    return min(pool, key=lambda p: p.id)


def _repoint_reviewers(session: Session, dup_id: int, canon_id: int) -> None:
    pr_ids = [
        row[0]
        for row in session.execute(
            select(pr_reviewers.c.pull_request_id).where(
                pr_reviewers.c.person_id == dup_id
            )
        ).all()
    ]
    for pr_id in pr_ids:
        already = session.execute(
            select(pr_reviewers.c.person_id).where(
                pr_reviewers.c.pull_request_id == pr_id,
                pr_reviewers.c.person_id == canon_id,
            )
        ).first()
        cond = (
            (pr_reviewers.c.pull_request_id == pr_id)
            & (pr_reviewers.c.person_id == dup_id)
        )
        if already:  # canonical is already a reviewer here — drop the duplicate link
            session.execute(sql_delete(pr_reviewers).where(cond))
        else:
            session.execute(update(pr_reviewers).where(cond).values(person_id=canon_id))


def _merge_pair(session: Session, dup: Person, canonical: Person) -> None:
    # Capture the duplicate's identity before deleting it.
    captured = {f: getattr(dup, f) for f in _IDENTITY_FIELDS}

    for model, column in _FK_TARGETS:
        session.execute(
            update(model)
            .where(getattr(model, column) == dup.id)
            .values(**{column: canonical.id})
        )
    _repoint_reviewers(session, dup.id, canonical.id)

    # Delete the duplicate first so its unique identity values are freed before we
    # copy them onto the canonical row (avoids a transient unique-constraint clash).
    session.delete(dup)
    session.flush()
    for field_name, value in captured.items():
        if getattr(canonical, field_name) in (None, "") and value not in (None, ""):
            setattr(canonical, field_name, value)
    session.flush()


def merge_people(session: Session) -> IdentityResult:
    before = session.scalar(select(func.count()).select_from(Person)) or 0

    by_email: dict[str, list[Person]] = defaultdict(list)
    for person in session.scalars(select(Person)).all():
        email = _norm_email(person.email)
        if email:
            by_email[email].append(person)

    merges: list[Merge] = []
    for email, group in by_email.items():
        if len(group) < 2:
            continue
        canonical = _pick_canonical(group)
        for dup in group:
            if dup.id == canonical.id:
                continue
            _merge_pair(session, dup, canonical)
            merges.append(Merge(canonical.id, dup.id, "email", email))

    session.flush()
    after = session.scalar(select(func.count()).select_from(Person)) or 0
    return IdentityResult(people_before=before, people_after=after, merges=merges)
