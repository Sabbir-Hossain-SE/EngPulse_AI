"""The normalized schema creates cleanly and links PRs ↔ people."""

from __future__ import annotations

from engpulse.db.base import Base
from engpulse.db.models import Person, PullRequest, Repository


def test_expected_tables_are_registered():
    tables = set(Base.metadata.tables)
    assert {
        "repositories",
        "people",
        "pull_requests",
        "commits",
        "issues",
        "ci_runs",
        "messages",
        "insights",
        "scores",
        "pr_reviewers",
    } <= tables


def test_pr_author_and_reviewer_links_persist(db_session):
    repo = Repository(github_id=1, full_name="acme/widgets", name="widgets")
    author = Person(github_user_id=10, github_login="alice", name="alice")
    reviewer = Person(github_user_id=11, github_login="bob", name="bob")
    db_session.add_all([repo, author, reviewer])
    db_session.flush()

    pr = PullRequest(
        repo_id=repo.id,
        number=1,
        title="first pr",
        state="open",
        author_id=author.id,
        reviewers=[reviewer],
    )
    db_session.add(pr)
    db_session.commit()

    fetched = db_session.get(PullRequest, pr.id)
    assert fetched.author.github_login == "alice"
    assert [r.github_login for r in fetched.reviewers] == ["bob"]
    assert fetched.repo.full_name == "acme/widgets"
