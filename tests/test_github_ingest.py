"""Sub-step 2.1 — GitHub + CI ingestion: DTOs, linking, cursors, audit, idempotency."""

from __future__ import annotations

import asyncio

from engpulse.connectors.github.client import FixtureGitHubClient
from engpulse.connectors.github.normalize import is_bugfix, review_facts
from engpulse.db.models import (
    CIRun,
    Commit,
    Person,
    PullRequest,
    Repository,
    SyncAudit,
    SyncCursor,
)
from engpulse.ingest.github_ingest import _fetch, _persist, _summarize_only

SCOPE = "engpulse-demo/demo-repo"


def _bundle(fixtures_dir):
    client = FixtureGitHubClient(fixtures_dir)
    return asyncio.run(_fetch(client, "engpulse-demo", "demo-repo", 50, 100, 100))


async def test_new_dtos_parse(fixtures_dir):
    client = FixtureGitHubClient(fixtures_dir)
    prs = await client.list_pull_requests("o", "r", limit=50)
    commits = await client.list_commits("o", "r", limit=100)
    runs = await client.list_workflow_runs("o", "r", limit=100)
    reviews = await client.list_reviews("o", "r", 101)

    assert prs[0].head_sha == "aaa101sha"
    assert commits[0].sha == "aaa101sha" and commits[0].author_login == "alice"
    assert runs[0].conclusion == "failure" and runs[0].head_sha == "aaa101sha"
    assert {r.reviewer_login for r in reviews} == {"bob", "carol"}


def test_is_bugfix_heuristic():
    assert is_bugfix("Fix flaky test") is True
    assert is_bugfix("Hotfix: guard nil") is True
    assert is_bugfix("Add new feature") is False
    assert is_bugfix(None) is False


def test_review_facts_first_and_rounds(fixtures_dir):
    bundle = _bundle(fixtures_dir)
    facts_101 = review_facts(bundle.reviews[101])
    assert facts_101["review_rounds"] == 2
    assert facts_101["first_review_at"].isoformat().startswith("2026-06-01T15:00")
    assert review_facts(bundle.reviews[103]) == {
        "first_review_at": None,
        "review_rounds": 0,
    }


def test_persist_counts_and_ci_linking(db_session, fixtures_dir):
    report = _persist(db_session, SCOPE, _bundle(fixtures_dir))
    db_session.commit()

    assert report.persisted is True
    assert report.pull_requests == 3
    assert report.reviews == 3
    assert report.commits == 4
    assert report.ci_runs == 4
    assert report.ci_runs_linked == 3  # 3 runs match a PR head sha; Nightly does not

    assert db_session.query(Repository).count() == 1
    assert db_session.query(PullRequest).count() == 3
    assert db_session.query(Commit).count() == 4
    assert db_session.query(CIRun).count() == 4
    assert db_session.query(Person).count() == 3  # alice, bob, carol

    # The unlinked Nightly run has no PR; the two CI runs for PR 101 link to it.
    pr101 = db_session.query(PullRequest).filter(PullRequest.number == 101).one()
    linked = db_session.query(CIRun).filter(CIRun.pull_request_id == pr101.id).all()
    assert len(linked) == 2
    assert {r.conclusion for r in linked} == {"failure", "success"}
    assert {p.github_login for p in pr101.reviewers} == {"bob", "carol"}
    assert pr101.review_rounds == 2


def test_bugfix_flag_persisted(db_session, fixtures_dir):
    _persist(db_session, SCOPE, _bundle(fixtures_dir))
    db_session.commit()
    bugfixes = db_session.query(Commit).filter(Commit.is_bugfix.is_(True)).count()
    assert bugfixes == 2  # "Fix flaky..." and "Hotfix..."; "Add"/"Bump" are not fixes


def test_cursors_and_audit_written(db_session, fixtures_dir):
    _persist(db_session, SCOPE, _bundle(fixtures_dir))
    db_session.commit()

    cursors = {c.resource: c for c in db_session.query(SyncCursor).all()}
    assert set(cursors) == {"pull_requests", "commits", "ci_runs"}
    assert cursors["pull_requests"].updated_since.isoformat().startswith("2026-06-05")
    assert cursors["commits"].updated_since.isoformat().startswith("2026-06-07")
    assert cursors["ci_runs"].updated_since.isoformat().startswith("2026-06-08")

    audits = {a.resource: a for a in db_session.query(SyncAudit).all()}
    assert all(a.status == "ok" for a in audits.values())
    assert audits["ci_runs"].records_seen == 4
    assert audits["commits"].records_written == 4


def test_ingestion_is_idempotent(db_session, fixtures_dir):
    _persist(db_session, SCOPE, _bundle(fixtures_dir))
    db_session.commit()
    _persist(db_session, SCOPE, _bundle(fixtures_dir))
    db_session.commit()

    assert db_session.query(Repository).count() == 1
    assert db_session.query(PullRequest).count() == 3
    assert db_session.query(Commit).count() == 4
    assert db_session.query(CIRun).count() == 4
    assert db_session.query(Person).count() == 3
    assert db_session.query(SyncCursor).count() == 3  # cursors are unique, not appended
    assert db_session.query(SyncAudit).count() == 6   # audit is a log: 3 per run × 2


def test_dry_run_summary(fixtures_dir):
    report = _summarize_only(_bundle(fixtures_dir))
    assert report.persisted is False
    assert report.pull_requests == 3
    assert report.commits == 4
    assert report.ci_runs == 4
    assert report.ci_runs_linked == 3
