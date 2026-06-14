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
    author_login: str | None = None
    author_id: int | None = None
    created_at: datetime | None = None
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None
    requested_reviewers: list[dict] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "PullRequestDTO":
        user = data.get("user") or {}
        return cls(
            id=data["id"],
            number=data["number"],
            title=data.get("title"),
            state=data.get("state"),
            html_url=data.get("html_url"),
            author_login=user.get("login"),
            author_id=user.get("id"),
            created_at=data.get("created_at"),
            merged_at=data.get("merged_at"),
            closed_at=data.get("closed_at"),
            additions=data.get("additions"),
            deletions=data.get("deletions"),
            changed_files=data.get("changed_files"),
            requested_reviewers=data.get("requested_reviewers") or [],
        )
