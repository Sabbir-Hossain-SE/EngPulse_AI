"""Sub-step 3.4 — the consolidated evaluation harness over the labeled corpus."""

from __future__ import annotations

from engpulse.eval import run_evaluation


def test_harness_scores_every_task_perfectly():
    report = run_evaluation()
    scores = {s["detector"]: s for s in report.scores}

    # All five labeled tasks are covered.
    assert set(scores) == {
        "stale_pr", "flaky_test", "deadline_drift", "pr_issue_link", "identity_merge",
    }
    # The corpus is designed to be fully detectable: every task is perfect.
    for detector, s in scores.items():
        assert s["precision"] == 1.0, detector
        assert s["recall"] == 1.0, detector
        assert s["f1"] == 1.0, detector

    assert report.macro_precision == 1.0
    assert report.macro_recall == 1.0


def test_harness_link_and_identity_counts():
    report = run_evaluation()
    scores = {s["detector"]: s for s in report.scores}
    # 3 PR↔issue links and 2 identity merges expected, all true positives.
    assert scores["pr_issue_link"]["tp"] == 3
    assert scores["pr_issue_link"]["fp"] == 0
    assert scores["identity_merge"]["tp"] == 2
    assert scores["identity_merge"]["fp"] == 0


def test_harness_is_self_contained_and_repeatable():
    # No DB/services required, and two runs agree (deterministic).
    first = run_evaluation()
    second = run_evaluation()
    assert first.scores == second.scores
    assert first.headline() == second.headline()
