"""Sub-step 8.1 — consolidated eval report + determinism/regression check."""

from __future__ import annotations

from engpulse.eval import run_evaluation
from engpulse.eval.harness import check_consistency
from engpulse.eval.report import render_eval_report


def test_evaluation_is_deterministic():
    assert check_consistency() is True


def test_report_renders_all_sections():
    report = run_evaluation()
    md = render_eval_report(report, deterministic=True)

    assert "# EngPulse — Evaluation Report" in md
    assert "## Detectors & entity resolution" in md
    assert "## Ask EngPulse agent" in md
    assert "## Determinism / regression" in md
    # Every scored task shows up in the table.
    for s in report.scores:
        assert s["detector"] in md
    # Headline macro line present.
    assert "Macro precision" in md
    assert "identical scores: yes" in md


def test_report_flags_non_determinism():
    report = run_evaluation()
    md = render_eval_report(report, deterministic=False)
    assert "identical scores: NO" in md
