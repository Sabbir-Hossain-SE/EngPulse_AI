"""PR & Code-Review Flow Analyzer (Module B).

Deterministic per-PR metrics and review-flow detectors over the normalized graph.
Every flag carries the source PR as evidence. No LLM, fully reproducible given an
``as_of`` reference time.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from engpulse.db.models import PullRequest, Repository
from engpulse.metrics.thresholds import Thresholds, load_thresholds
from engpulse.metrics.types import Severity, days_between, hours_between

_SEVERITY = {
    "stale": Severity.MEDIUM,
    "abandoned": Severity.HIGH,
    "unreviewed": Severity.LOW,
    "oversized": Severity.LOW,
    "merged_without_review": Severity.HIGH,
    "review_bottleneck": Severity.MEDIUM,
}


class PRMetrics(BaseModel):
    number: int
    id: int
    title: str | None = None
    state: str | None = None
    author: str | None = None
    size_lines: int = 0
    size_files: int | None = None
    review_rounds: int = 0
    time_to_first_review_hours: float | None = None
    time_to_merge_hours: float | None = None
    age_days: float | None = None
    reviewers: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class Flag(BaseModel):
    type: str
    severity: str
    pr_number: int | None = None
    evidence: dict = Field(default_factory=dict)


class PRFlowReport(BaseModel):
    repo: str
    as_of: datetime
    pull_requests: list[PRMetrics] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    reviewer_load: dict[str, int] = Field(default_factory=dict)
    bottleneck_reviewers: list[str] = Field(default_factory=list)

    def flagged_pr_numbers(self, flag_type: str) -> set[int]:
        return {f.pr_number for f in self.flags
                if f.type == flag_type and f.pr_number is not None}

    def counts_by_type(self) -> dict[str, int]:
        return dict(Counter(f.type for f in self.flags))


def _reviewer_names(pr: PullRequest) -> list[str]:
    return [p.github_login or p.name or str(p.id) for p in pr.reviewers]


def compute_pr_flow(
    session: Session,
    repo_full_name: str,
    thresholds: Thresholds | None = None,
    as_of: datetime | None = None,
) -> PRFlowReport:
    thresholds = thresholds or load_thresholds()
    cfg = thresholds.pr_flow
    as_of = as_of or datetime.now(timezone.utc)

    repo = session.scalars(
        select(Repository).where(Repository.full_name == repo_full_name)
    ).first()
    report = PRFlowReport(repo=repo_full_name, as_of=as_of)
    if repo is None:
        return report

    prs = session.scalars(
        select(PullRequest)
        .where(PullRequest.repo_id == repo.id)
        .options(selectinload(PullRequest.reviewers), selectinload(PullRequest.author))
        .order_by(PullRequest.number)
    ).all()

    reviewer_load: Counter[str] = Counter()
    for pr in prs:
        reviewers = _reviewer_names(pr)
        reviewer_load.update(reviewers)
        size_lines = (pr.additions or 0) + (pr.deletions or 0)
        last_activity = pr.source_updated_at or pr.pr_created_at
        age_days = days_between(last_activity, as_of)
        is_open = (pr.state or "").lower() == "open"
        is_merged = pr.merged_at is not None

        flags: list[str] = []
        if is_open and age_days is not None and age_days > cfg.abandoned_pr_days:
            flags.append("abandoned")
        elif is_open and age_days is not None and age_days > cfg.stale_pr_days:
            flags.append("stale")
        if is_open and (pr.review_rounds or 0) == 0:
            flags.append("unreviewed")
        if size_lines > cfg.oversized_pr_lines or (
            pr.changed_files or 0
        ) > cfg.oversized_pr_files:
            flags.append("oversized")
        if is_merged and (pr.review_rounds or 0) == 0:
            flags.append("merged_without_review")

        report.pull_requests.append(PRMetrics(
            number=pr.number, id=pr.id, title=pr.title, state=pr.state,
            author=(pr.author.github_login if pr.author else None),
            size_lines=size_lines, size_files=pr.changed_files,
            review_rounds=pr.review_rounds or 0,
            time_to_first_review_hours=hours_between(pr.pr_created_at, pr.first_review_at),
            time_to_merge_hours=hours_between(pr.pr_created_at, pr.merged_at),
            age_days=age_days, reviewers=reviewers, flags=flags,
        ))
        for flag_type in flags:
            report.flags.append(Flag(
                type=flag_type, severity=_SEVERITY[flag_type].value,
                pr_number=pr.number,
                evidence={"pr_id": pr.id, "number": pr.number, "url": pr.html_url},
            ))

    # Review bottleneck: a reviewer handling a disproportionate share of reviews.
    total = sum(reviewer_load.values())
    report.reviewer_load = dict(reviewer_load)
    if total > 0:
        for reviewer, count in reviewer_load.items():
            if count / total > cfg.reviewer_concentration and len(reviewer_load) > 1:
                report.bottleneck_reviewers.append(reviewer)
                report.flags.append(Flag(
                    type="review_bottleneck",
                    severity=_SEVERITY["review_bottleneck"].value,
                    evidence={"reviewer": reviewer, "share": round(count / total, 2)},
                ))
    return report
