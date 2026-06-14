"""Sub-step 2.2 — Linear ingestion: DTOs, drift/re-estimation, cursor, idempotency."""

from __future__ import annotations

import asyncio

from engpulse.connectors.linear.client import FixtureLinearClient
from engpulse.connectors.linear.normalize import (
    estimate_history,
    original_due_date,
    to_issue,
)
from engpulse.db.models import Issue, Person, SyncAudit, SyncCursor
from engpulse.ingest.linear_ingest import _persist, _summarize_only

SCOPE = "linear:ENG"


def _issues(fixtures_dir, team_key="ENG"):
    client = FixtureLinearClient(fixtures_dir)
    return asyncio.run(client.list_issues(team_key=team_key))


async def test_fixture_client_parses_and_filters(fixtures_dir):
    client = FixtureLinearClient(fixtures_dir)
    issues = await client.list_issues(team_key="ENG")
    assert [i.identifier for i in issues] == ["ENG-101", "ENG-102", "ENG-103"]
    assert issues[0].estimate == 3
    assert issues[0].assignee_email == "alice@example.com"
    assert issues[0].status == "In Progress"
    assert len(issues[0].transitions) == 4
    # team filter excludes everything when no match
    assert await client.list_issues(team_key="OPS") == []


def test_deadline_drift_and_reestimation_are_derived(fixtures_dir):
    issues = {i.identifier: i for i in _issues(fixtures_dir)}
    eng101 = issues["ENG-101"]

    assert original_due_date(eng101).date().isoformat() == "2026-06-05"
    assert eng101.due_date.date().isoformat() == "2026-06-20"  # drift: original != current

    est = estimate_history(eng101)
    assert len(est) == 1 and est[0]["from"] == 2 and est[0]["to"] == 3

    # An issue with no history derives no estimate changes and no drift.
    eng103 = issues["ENG-103"]
    assert estimate_history(eng103) == []
    assert original_due_date(eng103) is None


def test_to_issue_maps_fields(fixtures_dir):
    eng101 = {i.identifier: i for i in _issues(fixtures_dir)}["ENG-101"]
    issue = to_issue(eng101)
    assert isinstance(issue, Issue)
    assert issue.key == "ENG-101"
    assert issue.external_id == "lin-issue-101"
    assert issue.project == "Reliability"
    assert issue.team_key == "ENG"
    assert issue.labels == ["backend"]
    assert len(issue.transitions) == 4


def test_persist_counts_and_assignees(db_session, fixtures_dir):
    report = _persist(db_session, SCOPE, _issues(fixtures_dir))
    db_session.commit()

    assert report.persisted is True
    assert report.issues == 3
    assert report.assignees == 2  # alice, bob
    assert report.with_due_drift == 1  # ENG-101
    assert report.with_reestimation == 1  # ENG-101

    assert db_session.query(Issue).count() == 3
    assert db_session.query(Person).count() == 2
    eng101 = db_session.query(Issue).filter(Issue.key == "ENG-101").one()
    assert eng101.assignee.email == "alice@example.com"
    assert eng101.status == "In Progress"


def test_cursor_and_audit_written(db_session, fixtures_dir):
    _persist(db_session, SCOPE, _issues(fixtures_dir))
    db_session.commit()

    cursor = db_session.query(SyncCursor).filter(
        SyncCursor.source == "linear", SyncCursor.resource == "issues"
    ).one()
    assert cursor.updated_since.isoformat().startswith("2026-06-08")

    audit = db_session.query(SyncAudit).filter(SyncAudit.source == "linear").one()
    assert audit.status == "ok"
    assert audit.records_seen == 3 and audit.records_written == 3


def test_ingestion_is_idempotent(db_session, fixtures_dir):
    _persist(db_session, SCOPE, _issues(fixtures_dir))
    db_session.commit()
    _persist(db_session, SCOPE, _issues(fixtures_dir))
    db_session.commit()

    assert db_session.query(Issue).count() == 3
    assert db_session.query(Person).count() == 2
    assert db_session.query(SyncCursor).count() == 1
    assert db_session.query(SyncAudit).count() == 2  # one per run


def test_dry_run_summary(fixtures_dir):
    report = _summarize_only(SCOPE, _issues(fixtures_dir))
    assert report.persisted is False
    assert report.issues == 3
    assert report.with_due_drift == 1
    assert report.with_reestimation == 1
