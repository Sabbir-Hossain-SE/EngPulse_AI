"""Pure DTO → ORM normalization.

These functions are deliberately side-effect free (no DB, no network): given a
DTO they return a detached ORM instance. That keeps the mapping fully unit-
testable offline and isolates "what GitHub shape means in our schema" from the
persistence/upsert logic in ``ingest``.
"""

from __future__ import annotations

from engpulse.connectors.github.schemas import PullRequestDTO, RepositoryDTO
from engpulse.db.models import Person, PullRequest, Repository


def to_repository(dto: RepositoryDTO) -> Repository:
    return Repository(
        github_id=dto.id,
        full_name=dto.full_name,
        name=dto.name,
        default_branch=dto.default_branch,
        html_url=dto.html_url,
        last_activity_at=dto.pushed_at,
    )


def to_person_from_author(dto: PullRequestDTO) -> Person | None:
    if dto.author_id is None and not dto.author_login:
        return None
    return Person(
        github_user_id=dto.author_id,
        github_login=dto.author_login,
        name=dto.author_login,
    )


def to_person_from_reviewer(raw: dict) -> Person | None:
    if not raw:
        return None
    return Person(
        github_user_id=raw.get("id"),
        github_login=raw.get("login"),
        name=raw.get("login"),
    )


def to_pull_request(
    dto: PullRequestDTO, repo_id: int | None = None, author_id: int | None = None
) -> PullRequest:
    return PullRequest(
        github_id=dto.id,
        repo_id=repo_id,
        number=dto.number,
        title=dto.title,
        state=dto.state,
        html_url=dto.html_url,
        author_id=author_id,
        pr_created_at=dto.created_at,
        merged_at=dto.merged_at,
        closed_at=dto.closed_at,
        additions=dto.additions,
        deletions=dto.deletions,
        changed_files=dto.changed_files,
    )
