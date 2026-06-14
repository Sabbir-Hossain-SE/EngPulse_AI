"""Pure DTO → ORM normalization.

These functions are deliberately side-effect free (no DB, no network): given a
DTO they return a detached ORM instance. That keeps the mapping fully unit-
testable offline and isolates "what GitHub shape means in our schema" from the
persistence/upsert logic in ``ingest``.
"""

from __future__ import annotations

from engpulse.connectors.github.schemas import (
    CIRunDTO,
    CommitDTO,
    PullRequestDTO,
    RepositoryDTO,
    ReviewDTO,
)
from engpulse.db.models import CIRun, Commit, Person, PullRequest, Repository

# Substrings that mark a commit as a bug-fix (used by the tech-debt module later).
_BUGFIX_MARKERS = ("fix", "bug", "hotfix", "patch", "regression")


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
        head_sha=dto.head_sha,
        head_ref=dto.head_ref,
        body=dto.body,
        source_updated_at=dto.updated_at,
        author_id=author_id,
        pr_created_at=dto.created_at,
        merged_at=dto.merged_at,
        closed_at=dto.closed_at,
        additions=dto.additions,
        deletions=dto.deletions,
        changed_files=dto.changed_files,
    )


def to_person_from_commit(dto: CommitDTO) -> Person | None:
    if dto.author_id is None and not dto.author_login:
        return None
    return Person(
        github_user_id=dto.author_id,
        github_login=dto.author_login,
        name=dto.author_login,
    )


def is_bugfix(message: str | None) -> bool:
    if not message:
        return False
    first_line = message.splitlines()[0].lower()
    return any(marker in first_line for marker in _BUGFIX_MARKERS)


def to_commit(
    dto: CommitDTO, repo_id: int | None = None, author_id: int | None = None
) -> Commit:
    return Commit(
        sha=dto.sha,
        repo_id=repo_id,
        author_id=author_id,
        message=dto.message,
        is_bugfix=is_bugfix(dto.message),
        committed_at=dto.committed_at,
    )


def to_ci_run(
    dto: CIRunDTO, repo_id: int | None = None, pull_request_id: int | None = None
) -> CIRun:
    duration = None
    if dto.run_started_at and dto.updated_at and dto.conclusion:
        duration = max(0.0, (dto.updated_at - dto.run_started_at).total_seconds())
    return CIRun(
        github_id=dto.id,
        repo_id=repo_id,
        pull_request_id=pull_request_id,
        commit_sha=dto.head_sha,
        workflow=dto.workflow,
        status=dto.status,
        conclusion=dto.conclusion,
        run_attempt=dto.run_attempt,
        duration_seconds=duration,
        failed_tests=dto.failed_tests,
        run_started_at=dto.run_started_at,
        source_updated_at=dto.updated_at,
    )


def review_facts(reviews: list[ReviewDTO]) -> dict:
    """Deterministic review-flow facts derived from a PR's review events."""

    submitted = [r.submitted_at for r in reviews if r.submitted_at is not None]
    return {
        "first_review_at": min(submitted) if submitted else None,
        "review_rounds": len(reviews),
    }
