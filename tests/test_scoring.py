"""Sub-step 6.1 — project-health scoring: sub-scores, composite, banding."""

from __future__ import annotations

from datetime import datetime, timezone

from engpulse.eval.harness import ephemeral_corpus_session
from engpulse.scoring import compute_project_score, persist_project_score
from engpulse.scoring.config import ScoringConfig, load_scoring_config

AS_OF = datetime(2026, 6, 14, tzinfo=timezone.utc)


def test_band_thresholds():
    cfg = ScoringConfig()
    assert cfg.band_for(95) == "Healthy"
    assert cfg.band_for(80) == "Watch"
    assert cfg.band_for(70) == "At Risk"
    assert cfg.band_for(40) == "Critical"


def test_config_loads_from_yaml():
    cfg = load_scoring_config()
    assert cfg.weights["review_flow"] == 0.30
    assert cfg.penalty("high") == 20


def test_corpus_score_is_explainable_and_at_risk():
    session = ephemeral_corpus_session()
    score = compute_project_score(session, "acme/payments", team_key="PAY", as_of=AS_OF)

    subs = {s.name: s for s in score.sub_scores}
    # review_flow: PR#1 abandoned(20) + unreviewed(5) = 25 → 75
    assert subs["review_flow"].score == 75
    # delivery: stale(10)+drift(20)+re-est(5)+done-without-merged-PR(20) = 55 → 45
    assert subs["delivery"].score == 45
    # ci_test: one flaky × medium(10) → 90
    assert subs["ci_test"].score == 90
    # knowledge: one SPOF high(20) → 80
    assert subs["knowledge"].score == 80

    # composite = 75*.3 + 45*.3 + 90*.2 + 80*.2 = 70.0
    assert score.composite == 70.0
    assert score.band == "At Risk"


def test_persist_records_score_and_delta():
    session = ephemeral_corpus_session()
    first = compute_project_score(session, "acme/payments", team_key="PAY", as_of=AS_OF)
    row1 = persist_project_score(session, first)
    assert row1 is not None and row1.delta is None  # first score → no delta

    # Simulate an improved score and confirm the delta is computed.
    better = first.model_copy(update={"composite": 80.0, "band": "Watch"})
    row2 = persist_project_score(session, better)
    assert row2.delta == round(80.0 - first.composite, 2)
    assert session.get(type(row2), row2.id).band == "Watch"
