"""GitHub ingestion orchestrator (sub-step 2.1).

Pulls PRs (+ their reviews), commits, and GitHub Actions runs for one repo;
upserts them idempotently; links each CI run to its PR by head SHA; and records
per-resource audit rows + incremental cursors. Fetch is async; persistence is
synchronous and transactional. ``dry_run`` fetches + counts without touching the
DB, so the whole path verifies offline with no services.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from engpulse.connectors.github.client import GitHubClient, build_client
from engpulse.connectors.github.normalize import review_facts
from engpulse.connectors.github.schemas import (
    CIRunDTO,
    CommitDTO,
    PullRequestDTO,
    RepositoryDTO,
    ReviewDTO,
)
from engpulse.db.base import session_scope
from engpulse.ingest.audit import advance_cursor, audit_run
from engpulse.ingest.upsert import (
    upsert_ci_run,
    upsert_commit,
    upsert_person,
    upsert_pull_request,
    upsert_repository,
)
from engpulse.logging import get_logger

log = get_logger(__name__)
SOURCE = "github"


@dataclass
class IngestReport:
    repo_full_name: str
    pull_requests: int = 0
    reviews: int = 0
    commits: int = 0
    ci_runs: int = 0
    ci_runs_linked: int = 0
    persisted: bool = False
    audits: list[dict] = field(default_factory=list)


@dataclass
class _Bundle:
    repo: RepositoryDTO
    prs: list[PullRequestDTO]
    reviews: dict[int, list[ReviewDTO]]
    commits: list[CommitDTO]
    runs: list[CIRunDTO]


async def _fetch(
    client: GitHubClient,
    owner: str,
    name: str,
    pr_limit: int,
    commit_limit: int,
    run_limit: int,
) -> _Bundle:
    repo = await client.get_repository(owner, name)
    prs = await client.list_pull_requests(owner, name, limit=pr_limit)
    review_lists = await asyncio.gather(
        *(client.list_reviews(owner, name, pr.number) for pr in prs)
    )
    reviews = {pr.number: rl for pr, rl in zip(prs, review_lists)}
    commits = await client.list_commits(owner, name, limit=commit_limit)
    runs = await client.list_workflow_runs(owner, name, limit=run_limit)
    return _Bundle(repo=repo, prs=prs, reviews=reviews, commits=commits, runs=runs)


def _max_dt(values: list[datetime | None]) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _persist(session: Session, scope: str, bundle: _Bundle) -> IngestReport:
    report = IngestReport(repo_full_name=bundle.repo.full_name, persisted=True)
    repo = upsert_repository(session, bundle.repo)

    # --- Pull requests (+ reviews) -----------------------------------------
    head_sha_to_pr_id: dict[str, int] = {}
    with audit_run(session, SOURCE, "pull_requests", scope) as counters:
        for dto in bundle.prs:
            counters.seen += 1
            author = upsert_person(session, dto.author_id, dto.author_login)
            pr_reviews = bundle.reviews.get(dto.number, [])
            report.reviews += len(pr_reviews)
            pr = upsert_pull_request(
                session, dto, repo_id=repo.id,
                author_id=author.id if author else None,
                review_facts=review_facts(pr_reviews),
            )
            # Reviewers = requested reviewers ∪ people who actually submitted a review.
            people = []
            for raw in dto.requested_reviewers:
                rp = upsert_person(session, raw.get("id"), raw.get("login"))
                if rp:
                    people.append(rp)
            for rev in pr_reviews:
                rp = upsert_person(session, rev.reviewer_id, rev.reviewer_login)
                if rp:
                    people.append(rp)
            pr.reviewers = list({p.id: p for p in people}.values())
            counters.written += 1
            if dto.head_sha:
                head_sha_to_pr_id[dto.head_sha] = pr.id
        report.pull_requests = counters.written
    advance_cursor(session, SOURCE, "pull_requests", scope,
                   _max_dt([p.updated_at for p in bundle.prs]))

    # --- Commits ------------------------------------------------------------
    with audit_run(session, SOURCE, "commits", scope) as counters:
        for dto in bundle.commits:
            counters.seen += 1
            author = upsert_person(
                session, dto.author_id, dto.author_login, dto.author_email
            )
            upsert_commit(session, dto, repo_id=repo.id,
                          author_id=author.id if author else None)
            counters.written += 1
        report.commits = counters.written
    advance_cursor(session, SOURCE, "commits", scope,
                   _max_dt([c.committed_at for c in bundle.commits]))

    # --- CI runs (linked to PRs by head SHA) -------------------------------
    with audit_run(session, SOURCE, "ci_runs", scope) as counters:
        for dto in bundle.runs:
            counters.seen += 1
            pr_id = head_sha_to_pr_id.get(dto.head_sha) if dto.head_sha else None
            upsert_ci_run(session, dto, repo_id=repo.id, pull_request_id=pr_id)
            counters.written += 1
            if pr_id is not None:
                report.ci_runs_linked += 1
        report.ci_runs = counters.written
    advance_cursor(session, SOURCE, "ci_runs", scope,
                   _max_dt([r.updated_at for r in bundle.runs]))

    report.audits = _audit_summary(session, scope)
    return report


def _audit_summary(session: Session, scope: str) -> list[dict]:
    from engpulse.db.models import SyncAudit
    from sqlalchemy import select

    rows = session.scalars(
        select(SyncAudit).where(SyncAudit.scope == scope).order_by(SyncAudit.id)
    ).all()
    return [
        {"resource": r.resource, "seen": r.records_seen,
         "written": r.records_written, "status": r.status}
        for r in rows
    ]


def _summarize_only(bundle: _Bundle) -> IngestReport:
    linked = {p.head_sha for p in bundle.prs if p.head_sha}
    return IngestReport(
        repo_full_name=bundle.repo.full_name,
        pull_requests=len(bundle.prs),
        reviews=sum(len(v) for v in bundle.reviews.values()),
        commits=len(bundle.commits),
        ci_runs=len(bundle.runs),
        ci_runs_linked=sum(1 for r in bundle.runs if r.head_sha in linked),
        persisted=False,
    )


def ingest_github(
    repo: str,
    source: str = "fixture",
    pr_limit: int = 50,
    commit_limit: int = 100,
    run_limit: int = 100,
    dry_run: bool = False,
    fixtures_dir: str | None = None,
) -> IngestReport:
    """Ingest one repo's PRs, reviews, commits, and CI runs end-to-end."""

    if "/" not in repo:
        raise ValueError(f"Expected repo as 'owner/name', got '{repo}'")
    owner, name = repo.split("/", 1)

    client = build_client(source, fixtures_dir)
    bundle = asyncio.run(_fetch(client, owner, name, pr_limit, commit_limit, run_limit))
    log.info(
        "Fetched %s: %d PRs, %d commits, %d runs",
        bundle.repo.full_name, len(bundle.prs), len(bundle.commits), len(bundle.runs),
    )

    if dry_run:
        return _summarize_only(bundle)

    with session_scope() as session:
        return _persist(session, repo, bundle)
