"""Idempotent upserts: DTO → row, keyed by stable external identifiers.

These are the canonical persistence helpers every connector writes through, so
re-running a sync never duplicates rows. Pure DB logic — fetching lives in the
connectors, normalization in ``connectors.github.normalize``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from engpulse.connectors.github import normalize
from engpulse.connectors.github.schemas import (
    CIRunDTO,
    CommitDTO,
    PullRequestDTO,
    RepositoryDTO,
)
from engpulse.connectors.linear import normalize as linear_normalize
from engpulse.connectors.linear.schemas import LinearIssueDTO
from engpulse.db.models import CIRun, Commit, Issue, Person, PullRequest, Repository


def upsert_person(
    session: Session, github_user_id: int | None, login: str | None
) -> Person | None:
    if github_user_id is None and not login:
        return None
    stmt = select(Person)
    if github_user_id is not None:
        stmt = stmt.where(Person.github_user_id == github_user_id)
    else:
        stmt = stmt.where(Person.github_login == login)
    person = session.scalars(stmt).first()
    if person is None:
        person = Person(github_user_id=github_user_id, github_login=login, name=login)
        session.add(person)
        session.flush()
    else:  # backfill identity fields if a sparser record was created earlier
        if person.github_user_id is None and github_user_id is not None:
            person.github_user_id = github_user_id
        if not person.github_login and login:
            person.github_login = login
    return person


def upsert_person_tracker(
    session: Session,
    tracker_id: str | None,
    name: str | None,
    email: str | None,
) -> Person | None:
    """Upsert a tracker (Linear) identity, keyed by tracker id then email.

    GitHub-sourced people have no tracker_id, so they never collide here; the
    cross-system merge of these separate identities happens in sub-step 2.3.
    """

    if not tracker_id and not email:
        return None
    person = None
    if tracker_id:
        person = session.scalars(
            select(Person).where(Person.tracker_id == tracker_id)
        ).first()
    if person is None and email:
        person = session.scalars(select(Person).where(Person.email == email)).first()
    if person is None:
        person = Person(tracker_id=tracker_id, email=email, name=name)
        session.add(person)
        session.flush()
    else:
        if not person.tracker_id and tracker_id:
            person.tracker_id = tracker_id
        if not person.email and email:
            person.email = email
        if not person.name and name:
            person.name = name
    return person


def upsert_issue(
    session: Session, dto: LinearIssueDTO, assignee_id: int | None
) -> Issue:
    issue = session.scalars(
        select(Issue).where(Issue.key == dto.identifier)
    ).first()
    norm = linear_normalize.to_issue(dto, assignee_id=assignee_id)
    if issue is None:
        issue = norm
        session.add(issue)
    else:
        _apply(issue, norm, (
            "external_id", "title", "project", "team_key", "assignee_id",
            "status", "status_type", "estimate", "estimate_history",
            "original_due_date", "current_due_date", "transitions",
            "labels", "source_updated_at",
        ))
    session.flush()
    return issue


def _apply(target, source, attrs: tuple[str, ...]) -> None:
    for attr in attrs:
        setattr(target, attr, getattr(source, attr))


def upsert_repository(session: Session, dto: RepositoryDTO) -> Repository:
    repo = session.scalars(
        select(Repository).where(Repository.github_id == dto.id)
    ).first()
    norm = normalize.to_repository(dto)
    if repo is None:
        repo = norm
        session.add(repo)
    else:
        _apply(repo, norm,
               ("full_name", "name", "default_branch", "html_url", "last_activity_at"))
    session.flush()
    return repo


def upsert_pull_request(
    session: Session,
    dto: PullRequestDTO,
    repo_id: int,
    author_id: int | None,
    review_facts: dict | None = None,
) -> PullRequest:
    review_facts = review_facts or {}
    pr = session.scalars(
        select(PullRequest).where(
            PullRequest.repo_id == repo_id, PullRequest.number == dto.number
        )
    ).first()
    norm = normalize.to_pull_request(dto, repo_id=repo_id, author_id=author_id)
    norm.first_review_at = review_facts.get("first_review_at")
    norm.review_rounds = review_facts.get("review_rounds")
    if pr is None:
        pr = norm
        session.add(pr)
    else:
        _apply(pr, norm, (
            "github_id", "title", "state", "html_url", "head_sha", "source_updated_at",
            "author_id", "pr_created_at", "merged_at", "closed_at",
            "additions", "deletions", "changed_files",
            "first_review_at", "review_rounds",
        ))
    session.flush()
    return pr


def upsert_commit(
    session: Session, dto: CommitDTO, repo_id: int, author_id: int | None
) -> Commit:
    commit = session.scalars(select(Commit).where(Commit.sha == dto.sha)).first()
    norm = normalize.to_commit(dto, repo_id=repo_id, author_id=author_id)
    if commit is None:
        commit = norm
        session.add(commit)
    else:
        _apply(commit, norm,
               ("repo_id", "author_id", "message", "is_bugfix", "committed_at"))
    session.flush()
    return commit


def upsert_ci_run(
    session: Session, dto: CIRunDTO, repo_id: int, pull_request_id: int | None
) -> CIRun:
    run = session.scalars(select(CIRun).where(CIRun.github_id == dto.id)).first()
    norm = normalize.to_ci_run(dto, repo_id=repo_id, pull_request_id=pull_request_id)
    if run is None:
        run = norm
        session.add(run)
    else:
        _apply(run, norm, (
            "repo_id", "pull_request_id", "commit_sha", "workflow", "status",
            "conclusion", "run_attempt", "duration_seconds",
            "run_started_at", "source_updated_at",
        ))
    session.flush()
    return run
