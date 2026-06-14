"""Unified, normalized schema (PRD §9).

This is the *fact layer*: every later module reads from and writes into these
tables. Types are kept portable (generic ``JSON``, no Postgres-only columns) so
the schema can be created on SQLite for fast offline tests as well as on
Postgres in production. The pgvector extension is enabled at init time; vector
columns are introduced with the RAG/index module that needs them.

In the scaffold the GitHub read path populates ``Repository``, ``Person``, and
``PullRequest`` (+ the reviewer link). The remaining tables are defined now so
the shape is stable from milestone one.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engpulse.db.base import Base

# Many-to-many: which people are reviewers on which PRs.
pr_reviewers = Table(
    "pr_reviewers",
    Base.metadata,
    Column("pull_request_id", ForeignKey("pull_requests.id"), primary_key=True),
    Column("person_id", ForeignKey("people.id"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Repository(TimestampMixin, Base):
    """A repository / project — the top-level unit health is scored against."""

    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    default_branch: Mapped[str | None] = mapped_column(String(256))
    tracker_project_key: Mapped[str | None] = mapped_column(String(128))
    html_url: Mapped[str | None] = mapped_column(String(1024))
    health_score: Mapped[float | None] = mapped_column(Float)
    risk_band: Mapped[str | None] = mapped_column(String(32))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pull_requests: Mapped[list["PullRequest"]] = relationship(
        back_populates="repo", cascade="all, delete-orphan"
    )


class Person(TimestampMixin, Base):
    """A contributor, with an identity map across GitHub / tracker / Slack."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(256))
    role: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    github_user_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    github_login: Mapped[str | None] = mapped_column(String(256), index=True)
    tracker_id: Mapped[str | None] = mapped_column(String(256), unique=True, index=True)
    slack_id: Mapped[str | None] = mapped_column(String(256))
    teams: Mapped[list | None] = mapped_column(JSON)
    alert_history: Mapped[list | None] = mapped_column(JSON)


class PullRequest(TimestampMixin, Base):
    """A pull request and its review-flow facts (populated by the connector)."""

    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_pr_repo_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(String(32))
    html_url: Mapped[str | None] = mapped_column(String(1024))
    head_sha: Mapped[str | None] = mapped_column(String(64), index=True)
    head_ref: Mapped[str | None] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    linked_issue_id: Mapped[int | None] = mapped_column(ForeignKey("issues.id"))
    linked_issue_method: Mapped[str | None] = mapped_column(String(64))
    linked_issue_confidence: Mapped[float | None] = mapped_column(Float)

    pr_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    additions: Mapped[int | None] = mapped_column(Integer)
    deletions: Mapped[int | None] = mapped_column(Integer)
    changed_files: Mapped[int | None] = mapped_column(Integer)
    review_rounds: Mapped[int | None] = mapped_column(Integer)
    flags: Mapped[list | None] = mapped_column(JSON)

    repo: Mapped["Repository"] = relationship(back_populates="pull_requests")
    author: Mapped["Person | None"] = relationship(foreign_keys=[author_id])
    reviewers: Mapped[list["Person"]] = relationship(secondary=pr_reviewers)
    linked_issue: Mapped["Issue | None"] = relationship(
        back_populates="linked_prs", foreign_keys=[linked_issue_id]
    )


class Commit(TimestampMixin, Base):
    __tablename__ = "commits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    message: Mapped[str | None] = mapped_column(Text)
    additions: Mapped[int | None] = mapped_column(Integer)
    deletions: Mapped[int | None] = mapped_column(Integer)
    files_changed: Mapped[list | None] = mapped_column(JSON)
    is_bugfix: Mapped[bool] = mapped_column(Boolean, default=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Issue(TimestampMixin, Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(256), unique=True, index=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    project: Mapped[str | None] = mapped_column(String(256))
    team_key: Mapped[str | None] = mapped_column(String(64))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    status: Mapped[str | None] = mapped_column(String(64))
    status_type: Mapped[str | None] = mapped_column(String(64))
    estimate: Mapped[float | None] = mapped_column(Float)
    estimate_history: Mapped[list | None] = mapped_column(JSON)
    original_due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transitions: Mapped[list | None] = mapped_column(JSON)
    labels: Mapped[list | None] = mapped_column(JSON)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assignee: Mapped["Person | None"] = relationship(foreign_keys=[assignee_id])
    linked_prs: Mapped[list["PullRequest"]] = relationship(
        back_populates="linked_issue", foreign_keys="PullRequest.linked_issue_id"
    )


class CIRun(TimestampMixin, Base):
    __tablename__ = "ci_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    pull_request_id: Mapped[int | None] = mapped_column(ForeignKey("pull_requests.id"))
    commit_sha: Mapped[str | None] = mapped_column(String(64), index=True)
    workflow: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str | None] = mapped_column(String(64))
    conclusion: Mapped[str | None] = mapped_column(String(64))
    run_attempt: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    failed_tests: Mapped[list | None] = mapped_column(JSON)
    log_ref: Mapped[str | None] = mapped_column(String(1024))
    run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pull_request: Mapped["PullRequest | None"] = relationship(foreign_keys=[pull_request_id])


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str | None] = mapped_column(String(64))
    external_id: Mapped[str | None] = mapped_column(String(256), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    project_match: Mapped[str | None] = mapped_column(String(256))
    text: Mapped[str | None] = mapped_column(Text)
    blocker_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    unresolved_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    sentiment: Mapped[str | None] = mapped_column(String(32))
    escalation_flag: Mapped[bool] = mapped_column(Boolean, default=False)


class Insight(TimestampMixin, Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_refs: Mapped[list | None] = mapped_column(JSON)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    status: Mapped[str | None] = mapped_column(String(32))


class Score(TimestampMixin, Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    score_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    composite: Mapped[float | None] = mapped_column(Float)
    sub_scores: Mapped[dict | None] = mapped_column(JSON)
    band: Mapped[str | None] = mapped_column(String(32))
    delta: Mapped[float | None] = mapped_column(Float)


class SyncCursor(TimestampMixin, Base):
    """Per-source incremental cursor: how far a (source, resource, scope) is synced.

    ``scope`` is the unit being synced (e.g. a repo full name). ``updated_since``
    is the high-water mark advanced after each successful run so the next run only
    fetches records changed after it.
    """

    __tablename__ = "sync_cursors"
    __table_args__ = (
        UniqueConstraint("source", "resource", "scope", name="uq_cursor_src_res_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(512))
    updated_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str | None] = mapped_column(String(512))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncAudit(TimestampMixin, Base):
    """One row per sync run per resource: what was seen vs written, and status."""

    __tablename__ = "sync_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(512))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
