"""Sub-step 3.1 — PR-flow metrics/detectors + precision/recall vs the labels."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from engpulse.db.models import Person, PullRequest, Repository
from engpulse.eval import load_corpus, prf
from engpulse.ingest.github_ingest import _fetch as gh_fetch
from engpulse.ingest.github_ingest import _persist as gh_persist
from engpulse.metrics import compute_pr_flow
from engpulse.metrics.thresholds import Thresholds, load_thresholds


# --- thresholds ------------------------------------------------------------

def test_thresholds_load_defaults_and_yaml():
    defaults = Thresholds()
    assert defaults.pr_flow.stale_pr_days == 7
    # The committed YAML loads and matches the documented values.
    loaded = load_thresholds()
    assert loaded.pr_flow.oversized_pr_lines == 500


# --- per-PR metrics --------------------------------------------------------

def test_per_pr_metrics_and_flags(db_session):
    repo = Repository(github_id=1, full_name="acme/widgets", name="widgets")
    author = Person(github_user_id=10, github_login="alice")
    db_session.add_all([repo, author])
    db_session.flush()

    created = datetime(2026, 5, 1, tzinfo=timezone.utc)
    # An open, oversized, unreviewed, stale PR.
    pr = PullRequest(
        repo_id=repo.id, number=1, state="open", author_id=author.id,
        pr_created_at=created, source_updated_at=created,
        additions=600, deletions=20, changed_files=8, review_rounds=0,
    )
    db_session.add(pr)
    db_session.flush()

    as_of = datetime(2026, 6, 1, tzinfo=timezone.utc)  # 31 days later
    report = compute_pr_flow(db_session, "acme/widgets", as_of=as_of)

    m = report.pull_requests[0]
    assert m.size_lines == 620
    assert m.age_days == 31.0
    assert set(m.flags) == {"abandoned", "unreviewed", "oversized"}
    # Every flag carries its PR as evidence.
    assert all(f.evidence["number"] == 1 for f in report.flags if f.pr_number)


def test_time_to_review_and_merge(db_session):
    repo = Repository(github_id=2, full_name="acme/api", name="api")
    db_session.add(repo)
    db_session.flush()
    created = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    pr = PullRequest(
        repo_id=repo.id, number=5, state="closed",
        pr_created_at=created,
        first_review_at=datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc),
        merged_at=datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc),
        review_rounds=1, additions=10, deletions=2, changed_files=1,
        source_updated_at=created,
    )
    db_session.add(pr)
    db_session.flush()

    report = compute_pr_flow(db_session, "acme/api", as_of=created)
    m = report.pull_requests[0]
    assert m.time_to_first_review_hours == 6.0
    assert m.time_to_merge_hours == 24.0
    assert m.flags == []


# --- eval against the labeled corpus --------------------------------------

def test_stale_pr_detection_scores_perfect_on_corpus(db_session):
    corpus = load_corpus()
    owner, name = corpus.repo["full_name"].split("/", 1)
    bundle = asyncio.run(gh_fetch(corpus.github_client(), owner, name, 50, 100, 100))
    gh_persist(db_session, corpus.repo["full_name"], bundle)
    db_session.flush()

    as_of = datetime.combine(
        corpus.labels.as_of, datetime.min.time(), tzinfo=timezone.utc
    )
    report = compute_pr_flow(db_session, corpus.repo["full_name"], as_of=as_of)

    # "stale" target = open beyond the staleness threshold (abandoned is escalated stale).
    predicted = report.flagged_pr_numbers("stale") | report.flagged_pr_numbers("abandoned")
    expected = {s.pr_number for s in corpus.labels.stale_prs}
    assert predicted == {1}

    score = prf("stale_pr", predicted, expected)
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.f1 == 1.0
