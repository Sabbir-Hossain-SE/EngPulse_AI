"""Typed transfer objects for the GitHub connector.

These are the connector's *boundary contract*: the raw GitHub JSON is parsed
into these Pydantic models, and normalization (DTO → ORM) only ever reads
from them. Keeping a typed seam here means a GitHub API shape change is caught
in one place rather than rippling through the codebase.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RepositoryDTO(BaseModel):
    id: int
    full_name: str
    name: str
    owner_login: str
    default_branch: str | None = None
    html_url: str | None = None
    pushed_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict) -> "RepositoryDTO":
        return cls(
            id=data["id"],
            full_name=data["full_name"],
            name=data["name"],
            owner_login=data.get("owner", {}).get("login", ""),
            default_branch=data.get("default_branch"),
            html_url=data.get("html_url"),
            pushed_at=data.get("pushed_at"),
        )


class PullRequestDTO(BaseModel):
    id: int
    number: int
    title: str | None = None
    state: str | None = None
    html_url: str | None = None
    head_sha: str | None = None
    head_ref: str | None = None
    body: str | None = None
    author_login: str | None = None
    author_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None
    requested_reviewers: list[dict] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "PullRequestDTO":
        user = data.get("user") or {}
        head = data.get("head") or {}
        return cls(
            id=data["id"],
            number=data["number"],
            title=data.get("title"),
            state=data.get("state"),
            html_url=data.get("html_url"),
            head_sha=head.get("sha"),
            head_ref=head.get("ref"),
            body=data.get("body"),
            author_login=user.get("login"),
            author_id=user.get("id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            merged_at=data.get("merged_at"),
            closed_at=data.get("closed_at"),
            additions=data.get("additions"),
            deletions=data.get("deletions"),
            changed_files=data.get("changed_files"),
            requested_reviewers=data.get("requested_reviewers") or [],
        )


class ReviewDTO(BaseModel):
    id: int
    pr_number: int | None = None
    reviewer_login: str | None = None
    reviewer_id: int | None = None
    state: str | None = None  # APPROVED / CHANGES_REQUESTED / COMMENTED
    submitted_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict, pr_number: int | None = None) -> "ReviewDTO":
        user = data.get("user") or {}
        return cls(
            id=data["id"],
            pr_number=pr_number,
            reviewer_login=user.get("login"),
            reviewer_id=user.get("id"),
            state=data.get("state"),
            submitted_at=data.get("submitted_at"),
        )


class CommitDTO(BaseModel):
    sha: str
    message: str | None = None
    author_login: str | None = None
    author_id: int | None = None
    author_email: str | None = None
    committed_at: datetime | None = None
    files: list[str] = Field(default_factory=list)

    @staticmethod
    def _parse_files(raw) -> list[str]:
        # The live commit-detail endpoint returns [{"filename": ...}, ...];
        # the synthetic corpus uses a plain list of path strings.
        files: list[str] = []
        for item in raw or []:
            if isinstance(item, str):
                files.append(item)
            elif isinstance(item, dict) and item.get("filename"):
                files.append(item["filename"])
        return files

    @classmethod
    def from_api(cls, data: dict) -> "CommitDTO":
        author = data.get("author") or {}  # the GitHub user (may be null)
        commit = data.get("commit") or {}
        commit_author = commit.get("author") or {}
        return cls(
            sha=data["sha"],
            message=commit.get("message"),
            author_login=author.get("login"),
            author_id=author.get("id"),
            author_email=commit_author.get("email"),
            committed_at=commit_author.get("date"),
            files=cls._parse_files(data.get("files")),
        )


class CIRunDTO(BaseModel):
    id: int
    workflow: str | None = None
    head_sha: str | None = None
    status: str | None = None
    conclusion: str | None = None
    run_attempt: int | None = None
    run_started_at: datetime | None = None
    updated_at: datetime | None = None
    # Failing test names. The live Actions runs endpoint does not provide these;
    # they come from a log/JUnit parser (or the synthetic corpus) — consumed by
    # the test-level flaky detector when present.
    failed_tests: list[str] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "CIRunDTO":
        return cls(
            id=data["id"],
            workflow=data.get("name"),
            head_sha=data.get("head_sha"),
            status=data.get("status"),
            conclusion=data.get("conclusion"),
            run_attempt=data.get("run_attempt"),
            run_started_at=data.get("run_started_at"),
            updated_at=data.get("updated_at"),
            failed_tests=data.get("failed_tests") or [],
        )
