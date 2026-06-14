"""Typed ground-truth labels for the synthetic corpus.

These are the expected answers the eval harness scores detector and resolution
output against (precision/recall, faithfulness, etc.).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class StalePRLabel(BaseModel):
    pr_number: int
    min_age_days: int
    unreviewed: bool = False
    note: str | None = None


class FlakyTestLabel(BaseModel):
    test: str
    commit_sha: str
    note: str | None = None


class DeadlineDriftLabel(BaseModel):
    issue: str
    original_due: date
    current_due: date
    moves: int
    note: str | None = None


class BusFactorLabel(BaseModel):
    module: str
    owner: str
    contributors: list[str]
    contributor_count: int
    note: str | None = None


class PrIssueLinkLabel(BaseModel):
    pr_number: int
    issue: str
    method: str


class IdentityLabel(BaseModel):
    email: str
    github_login: str
    tracker_id: str


class CorpusLabels(BaseModel):
    as_of: date
    repo: str
    team_key: str
    description: str | None = None
    stale_prs: list[StalePRLabel] = Field(default_factory=list)
    flaky_tests: list[FlakyTestLabel] = Field(default_factory=list)
    deadline_drifts: list[DeadlineDriftLabel] = Field(default_factory=list)
    bus_factors: list[BusFactorLabel] = Field(default_factory=list)
    pr_issue_links: list[PrIssueLinkLabel] = Field(default_factory=list)
    identities: list[IdentityLabel] = Field(default_factory=list)
    people_before: int | None = None
    people_after: int | None = None
