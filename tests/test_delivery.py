"""Sub-step 3.3 — delivery/drift: cycle time, drift, re-estimation, gaps + eval."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from engpulse.db.models import Issue, PullRequest, Repository
from engpulse.eval import load_corpus, prf
from engpulse.ingest.github_ingest import _fetch as gh_fetch
from engpulse.ingest.github_ingest import _persist as gh_persist
from engpulse.ingest.linear_ingest import _persist as linear_persist
from engpulse.metrics import compute_delivery
from engpulse.resolve.identity import merge_people
from engpulse.resolve.pr_issue import link_prs_to_issues

UTC = timezone.utc


def test_deadline_drift_and_reestimation(db_session):
    issue = Issue(
        key="ENG-1", status="In Progress", status_type="started", estimate=5,
        estimate_history=[{"at": "2026-01-01T00:00:00+00:00", "from": 2, "to": 5}],
        original_due_date=datetime(2026, 5, 15, tzinfo=UTC),
        current_due_date=datetime(2026, 6, 30, tzinfo=UTC),
        transitions=[
            {"from_due_date": "2026-05-15", "to_due_date": "2026-05-30"},
            {"from_due_date": "2026-05-30", "to_due_date": "2026-06-30"},
        ],
        source_created_at=datetime(2026, 3, 1, tzinfo=UTC),
        source_updated_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    db_session.add(issue)
    db_session.flush()

    report = compute_delivery(db_session, as_of=datetime(2026, 6, 14, tzinfo=UTC))
    m = report.issues[0]
    assert m.due_moves == 2 and "deadline_drift" in m.flags
    assert m.reestimations == 1 and "re_estimation" in m.flags
    drift_flag = next(f for f in report.flags if f.type == "deadline_drift")
    assert drift_flag.evidence["moves"] == 2
    assert drift_flag.evidence["original_due"] == "2026-05-15"


def test_stale_issue_flagged(db_session):
    issue = Issue(
        key="ENG-9", status="In Progress", status_type="started",
        source_created_at=datetime(2026, 5, 1, tzinfo=UTC),
        source_updated_at=datetime(2026, 6, 1, tzinfo=UTC),  # 13 days before as_of
    )
    db_session.add(issue)
    db_session.flush()
    report = compute_delivery(db_session, as_of=datetime(2026, 6, 14, tzinfo=UTC))
    assert "stale_issue" in report.issues[0].flags
    assert report.wip_by_assignee == {}  # no assignee


def test_done_without_merged_pr_and_cycle_time(db_session):
    repo = Repository(github_id=1, full_name="acme/x", name="x")
    db_session.add(repo)
    db_session.flush()

    done_open = Issue(
        key="ENG-2", status="Done", status_type="completed",
        source_created_at=datetime(2026, 6, 1, tzinfo=UTC),
        source_updated_at=datetime(2026, 6, 5, tzinfo=UTC),
        transitions=[{"at": "2026-06-05T00:00:00+00:00",
                      "from_state": "In Progress", "to_state": "Done"}],
    )
    done_merged = Issue(
        key="ENG-3", status="Done", status_type="completed",
        source_created_at=datetime(2026, 6, 1, tzinfo=UTC),
        source_updated_at=datetime(2026, 6, 3, tzinfo=UTC),
        transitions=[{"at": "2026-06-03T00:00:00+00:00",
                      "from_state": "In Progress", "to_state": "Done"}],
    )
    db_session.add_all([done_open, done_merged])
    db_session.flush()
    db_session.add_all([
        PullRequest(repo_id=repo.id, number=1, state="open",
                    linked_issue_id=done_open.id, merged_at=None),
        PullRequest(repo_id=repo.id, number=2, state="closed",
                    linked_issue_id=done_merged.id,
                    merged_at=datetime(2026, 6, 3, tzinfo=UTC)),
    ])
    db_session.flush()

    report = compute_delivery(db_session, as_of=datetime(2026, 6, 14, tzinfo=UTC))
    assert report.flagged_issues("done_without_merged_pr") == {"ENG-2"}
    eng2 = next(i for i in report.issues if i.key == "ENG-2")
    assert eng2.cycle_time_days == 4.0


def test_deadline_drift_scores_perfect_on_corpus(db_session):
    corpus = load_corpus()
    issues = asyncio.run(corpus.linear_client().list_issues(team_key="PAY"))
    linear_persist(db_session, "linear:PAY", issues)
    db_session.flush()

    as_of = datetime.combine(corpus.labels.as_of, datetime.min.time(), tzinfo=UTC)
    report = compute_delivery(db_session, team_key="PAY", as_of=as_of)

    predicted = report.flagged_issues("deadline_drift")
    expected = {d.issue for d in corpus.labels.deadline_drifts}
    assert predicted == {"PAY-12"}
    score = prf("deadline_drift", predicted, expected)
    assert score.precision == 1.0 and score.recall == 1.0


def test_done_without_merged_pr_on_corpus(db_session):
    corpus = load_corpus()
    owner, name = corpus.repo["full_name"].split("/", 1)
    bundle = asyncio.run(gh_fetch(corpus.github_client(), owner, name, 50, 100, 100))
    gh_persist(db_session, corpus.repo["full_name"], bundle)
    linear_persist(
        db_session, "linear:PAY",
        asyncio.run(corpus.linear_client().list_issues(team_key="PAY")),
    )
    db_session.flush()
    link_prs_to_issues(db_session)
    merge_people(db_session)
    db_session.commit()

    as_of = datetime.combine(corpus.labels.as_of, datetime.min.time(), tzinfo=UTC)
    report = compute_delivery(db_session, team_key="PAY", as_of=as_of)
    # PAY-20 is Done but its only linked PR (#2) is open → accountability gap.
    assert "PAY-20" in report.flagged_issues("done_without_merged_pr")
