"""Knowledge-Silo / Bus-Factor Mapper — deterministic part (Module E).

Builds an ownership graph from commit→file history and flags single-points-of-
failure: a module concentrated in one (or very few) contributors that also has
real churn. The LLM-backed "who owns X and what's at risk" answering is layered
on top in sub-steps 4.2/4.3; this is the auditable, deterministic foundation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from engpulse.db.models import Commit, Repository
from engpulse.metrics.thresholds import Thresholds, load_thresholds
from engpulse.metrics.types import Severity


class OwnershipEntry(BaseModel):
    module: str
    owner: str | None = None
    contributors: list[str] = Field(default_factory=list)
    contributor_count: int = 0
    commit_count: int = 0
    ownership_share: float = 0.0
    last_touched: datetime | None = None
    flags: list[str] = Field(default_factory=list)


class KnowledgeRiskFlag(BaseModel):
    type: str
    severity: str
    module: str
    evidence: dict = Field(default_factory=dict)


class KnowledgeRiskReport(BaseModel):
    repo: str
    modules: list[OwnershipEntry] = Field(default_factory=list)
    flags: list[KnowledgeRiskFlag] = Field(default_factory=list)

    def flagged_modules(self) -> set[str]:
        return {f.module for f in self.flags}


def compute_knowledge_risk(
    session: Session,
    repo_full_name: str,
    thresholds: Thresholds | None = None,
) -> KnowledgeRiskReport:
    thresholds = thresholds or load_thresholds()
    cfg = thresholds.knowledge

    repo = session.scalars(
        select(Repository).where(Repository.full_name == repo_full_name)
    ).first()
    report = KnowledgeRiskReport(repo=repo_full_name)
    if repo is None:
        return report

    commits = session.scalars(
        select(Commit)
        .where(Commit.repo_id == repo.id)
        .options(selectinload(Commit.author))
    ).all()

    # file path -> author login -> commit count, plus last-touched timestamps.
    per_file_authors: dict[str, Counter] = defaultdict(Counter)
    per_file_last: dict[str, datetime] = {}
    for c in commits:
        login = (c.author.github_login or c.author.name) if c.author else "unknown"
        for path in (c.files_changed or []):
            per_file_authors[path][login] += 1
            if c.committed_at and (
                path not in per_file_last or c.committed_at > per_file_last[path]
            ):
                per_file_last[path] = c.committed_at

    for path, author_counts in per_file_authors.items():
        total = sum(author_counts.values())
        owner, owner_count = author_counts.most_common(1)[0]
        contributors = sorted(author_counts)
        share = round(owner_count / total, 4) if total else 0.0

        flags: list[str] = []
        if len(contributors) <= cfg.bus_factor_max_owners and total >= cfg.bus_factor_min_commits:
            flags.append("single_point_of_failure")

        report.modules.append(OwnershipEntry(
            module=path, owner=owner, contributors=contributors,
            contributor_count=len(contributors), commit_count=total,
            ownership_share=share, last_touched=per_file_last.get(path), flags=flags,
        ))
        for flag_type in flags:
            report.flags.append(KnowledgeRiskFlag(
                type=flag_type, severity=Severity.HIGH.value, module=path,
                evidence={"owner": owner, "commit_count": total,
                          "contributors": contributors},
            ))

    report.modules.sort(key=lambda m: m.commit_count, reverse=True)
    return report
