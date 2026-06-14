"""Sub-step 3.2 — CI/test-health: flaky detection, clustering, trends + eval."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from engpulse.db.models import CIRun, Repository
from engpulse.eval import load_corpus, prf
from engpulse.ingest.github_ingest import _fetch as gh_fetch
from engpulse.ingest.github_ingest import _persist as gh_persist
from engpulse.metrics import compute_ci_health


def _repo(db_session) -> Repository:
    repo = Repository(github_id=1, full_name="acme/widgets", name="widgets")
    db_session.add(repo)
    db_session.flush()
    return repo


def test_flaky_requires_flip_on_same_sha(db_session):
    repo = _repo(db_session)
    # Same SHA: one failure (test_x), one success → test_x is flaky.
    db_session.add_all([
        CIRun(github_id=1, repo_id=repo.id, commit_sha="s1", workflow="CI",
              conclusion="failure", failed_tests=["test_x"]),
        CIRun(github_id=2, repo_id=repo.id, commit_sha="s1", workflow="CI",
              conclusion="success", failed_tests=[]),
        # A test that only ever fails on its SHA (no success run) is NOT flaky.
        CIRun(github_id=3, repo_id=repo.id, commit_sha="s2", workflow="CI",
              conclusion="failure", failed_tests=["test_y"]),
    ])
    db_session.flush()

    report = compute_ci_health(db_session, "acme/widgets")
    flaky = {f.test: f for f in report.flaky_tests}
    assert set(flaky) == {"test_x"}
    assert flaky["test_x"].flip_rate == 0.5
    assert flaky["test_x"].fail_runs == 1 and flaky["test_x"].total_runs == 2
    assert flaky["test_x"].evidence_run_ids == [1, 2]


def test_failure_clusters_group_by_signature(db_session):
    repo = _repo(db_session)
    db_session.add_all([
        CIRun(github_id=10, repo_id=repo.id, commit_sha="a", workflow="CI",
              conclusion="failure", failed_tests=["test_a"]),
        CIRun(github_id=11, repo_id=repo.id, commit_sha="b", workflow="CI",
              conclusion="failure", failed_tests=["test_a"]),
        CIRun(github_id=12, repo_id=repo.id, commit_sha="c", workflow="CI",
              conclusion="failure", failed_tests=["test_b"]),
    ])
    db_session.flush()

    report = compute_ci_health(db_session, "acme/widgets")
    clusters = {c.signature: c for c in report.failure_clusters}
    assert clusters["test_a"].count == 2
    assert clusters["test_a"].run_ids == [10, 11]
    assert clusters["test_b"].count == 1


def test_duration_regression_flagged(db_session):
    repo = _repo(db_session)
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for i, dur in enumerate([100.0, 110.0, 300.0]):  # last >> first*(1.5)
        db_session.add(CIRun(
            github_id=20 + i, repo_id=repo.id, commit_sha=f"sha{i}", workflow="CI",
            conclusion="success", duration_seconds=dur,
            run_started_at=base.replace(day=1 + i),
        ))
    db_session.flush()

    report = compute_ci_health(db_session, "acme/widgets")
    trend = report.duration_trends[0]
    assert trend.runs == 3
    assert trend.first_seconds == 100.0 and trend.last_seconds == 300.0
    assert trend.regression is True


def test_flaky_detection_scores_perfect_on_corpus(db_session):
    corpus = load_corpus()
    owner, name = corpus.repo["full_name"].split("/", 1)
    bundle = asyncio.run(gh_fetch(corpus.github_client(), owner, name, 50, 100, 100))
    gh_persist(db_session, corpus.repo["full_name"], bundle)
    db_session.flush()

    report = compute_ci_health(db_session, corpus.repo["full_name"])
    predicted = report.flaky_keys()
    expected = {(f.test, f.commit_sha) for f in corpus.labels.flaky_tests}
    assert predicted == {("test_checkout_timeout", "f1aky00sha")}

    score = prf("flaky_test", predicted, expected)
    assert score.precision == 1.0 and score.recall == 1.0
