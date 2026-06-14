"""Sub-step 5.2 — agent eval: source recall, citation faithfulness, abstention."""

from __future__ import annotations

from engpulse.eval import load_corpus, run_evaluation
from engpulse.eval.harness import ephemeral_corpus_session, evaluate_agent


def test_corpus_has_a_labeled_question_set():
    labels = load_corpus().labels
    assert len(labels.agent_questions) >= 4
    assert any(q.answerable for q in labels.agent_questions)
    assert any(not q.answerable for q in labels.agent_questions)


def test_agent_eval_metrics_are_perfect_on_corpus():
    corpus = load_corpus()
    metrics = evaluate_agent(ephemeral_corpus_session(corpus), corpus)
    # The agent consults the right source for every answerable question…
    assert metrics["source_recall"] == 1.0
    # …never cites anything outside the gathered evidence…
    assert metrics["citation_faithfulness"] == 1.0
    # …and abstains/clarifies on every unanswerable one.
    assert metrics["correct_abstention"] == 1.0


def test_agent_metrics_surface_in_full_evaluation():
    report = run_evaluation()
    assert report.agent["questions"] >= 4
    assert report.agent["source_recall"] == 1.0
    assert report.agent["correct_abstention"] == 1.0
    # The detector tasks are unaffected.
    assert {s["detector"] for s in report.scores} >= {"bus_factor", "flaky_test"}
