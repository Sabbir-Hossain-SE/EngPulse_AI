"""The end-to-end read path: connector → normalize → upsert.

Fetching is async (the connector); persistence is plain synchronous SQLAlchemy.
The two are cleanly separated so the network step can be mocked/replayed and the
DB step can be exercised independently. ``--dry-run`` exercises fetch +
normalize and skips the DB entirely, so the read path can be verified with no
services running at all.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from engpulse.connectors.github.client import GitHubClient, build_client
from engpulse.connectors.github.normalize import (
    to_person_from_author,
    to_person_from_reviewer,
    to_pull_request,
    to_repository,
)
from engpulse.connectors.github.schemas import PullRequestDTO, RepositoryDTO
from engpulse.db.base import session_scope
from engpulse.db.models import Person, PullRequest, Repository
from engpulse.logging import get_logger

log = get_logger(__name__)


@dataclass
class SyncSummary:
    repo_full_name: str
    pull_requests: int = 0
    authors: int = 0
    reviewers: int = 0
    persisted: bool = False
    sample_pr_numbers: list[int] = field(default_factory=list)


async def _fetch(
    client: GitHubClient, owner: str, name: str, limit: int
) -> tuple[RepositoryDTO, list[PullRequestDTO]]:
    repo_dto = await client.get_repository(owner, name)
    pr_dtos = await client.list_pull_requests(owner, name, limit=limit)
    return repo_dto, pr_dtos


def _upsert_person(session: Session, gh_id: int | None, login: str | None) -> Person | None:
    if gh_id is None and not login:
        return None
    stmt = select(Person)
    if gh_id is not None:
        stmt = stmt.where(Person.github_user_id == gh_id)
    else:
        stmt = stmt.where(Person.github_login == login)
    person = session.scalars(stmt).first()
    if person is None:
        person = Person(github_user_id=gh_id, github_login=login, name=login)
        session.add(person)
        session.flush()
    return person


def _persist(
    session: Session, repo_dto: RepositoryDTO, pr_dtos: list[PullRequestDTO]
) -> SyncSummary:
    repo = session.scalars(
        select(Repository).where(Repository.github_id == repo_dto.id)
    ).first()
    normalized = to_repository(repo_dto)
    if repo is None:
        repo = normalized
        session.add(repo)
    else:
        for attr in ("full_name", "name", "default_branch", "html_url", "last_activity_at"):
            setattr(repo, attr, getattr(normalized, attr))
    session.flush()

    authors: set[int | str] = set()
    reviewers: set[int | str] = set()
    for dto in pr_dtos:
        author = _upsert_person(session, dto.author_id, dto.author_login)
        if author is not None:
            authors.add(author.github_user_id or author.github_login)

        pr = session.scalars(
            select(PullRequest).where(
                PullRequest.repo_id == repo.id, PullRequest.number == dto.number
            )
        ).first()
        normalized_pr = to_pull_request(dto, repo_id=repo.id,
                                        author_id=author.id if author else None)
        if pr is None:
            pr = normalized_pr
            session.add(pr)
        else:
            for attr in ("github_id", "title", "state", "html_url", "author_id",
                         "pr_created_at", "merged_at", "closed_at",
                         "additions", "deletions", "changed_files"):
                setattr(pr, attr, getattr(normalized_pr, attr))

        review_people = []
        for raw in dto.requested_reviewers:
            reviewer = _upsert_person(session, raw.get("id"), raw.get("login"))
            if reviewer is not None:
                review_people.append(reviewer)
                reviewers.add(reviewer.github_user_id or reviewer.github_login)
        pr.reviewers = review_people

    session.flush()
    return SyncSummary(
        repo_full_name=repo_dto.full_name,
        pull_requests=len(pr_dtos),
        authors=len(authors),
        reviewers=len(reviewers),
        persisted=True,
        sample_pr_numbers=[d.number for d in pr_dtos[:5]],
    )


def _summarize_only(repo_dto: RepositoryDTO, pr_dtos: list[PullRequestDTO]) -> SyncSummary:
    authors = {d.author_id or d.author_login for d in pr_dtos if d.author_id or d.author_login}
    reviewers = {
        r.get("id") or r.get("login")
        for d in pr_dtos
        for r in d.requested_reviewers
        if r.get("id") or r.get("login")
    }
    return SyncSummary(
        repo_full_name=repo_dto.full_name,
        pull_requests=len(pr_dtos),
        authors=len(authors),
        reviewers=len(reviewers),
        persisted=False,
        sample_pr_numbers=[d.number for d in pr_dtos[:5]],
    )


def sync_repository(
    repo: str,
    source: str = "fixture",
    limit: int = 20,
    dry_run: bool = False,
) -> SyncSummary:
    """Run the full read path for ``owner/name``.

    ``source`` is ``"live"`` or ``"fixture"``; ``dry_run`` fetches + normalizes
    but does not touch the database.
    """

    if "/" not in repo:
        raise ValueError(f"Expected repo as 'owner/name', got '{repo}'")
    owner, name = repo.split("/", 1)

    client = build_client(source)
    repo_dto, pr_dtos = asyncio.run(_fetch(client, owner, name, limit))
    log.info("Fetched %s with %d pull request(s)", repo_dto.full_name, len(pr_dtos))

    if dry_run:
        return _summarize_only(repo_dto, pr_dtos)

    with session_scope() as session:
        return _persist(session, repo_dto, pr_dtos)
