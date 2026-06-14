"""Module 5.1 — Ask EngPulse agent: planning, tool use, grounding, abstention."""

from __future__ import annotations

from datetime import datetime, timezone

from engpulse.agent import RuleBasedPlanner, build_agent
from engpulse.agent.planner import extract_subject, needs_clarification
from engpulse.eval.harness import ephemeral_corpus_session
from engpulse.llm import FakeChatClient, build_embedding_client
from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_index

AS_OF = datetime(2026, 6, 14, tzinfo=timezone.utc)


# --- planner ---------------------------------------------------------------

def test_rule_planner_routes_by_intent():
    planner = RuleBasedPlanner()
    own = [c.tool for c in planner.plan("who owns the auth tokens module")]
    assert "ownership" in own and own[-1] == "retrieval"

    risk = [c.tool for c in planner.plan("is the payments project at risk?")]
    assert "delivery" in risk

    ci = [c.tool for c in planner.plan("are there any flaky tests?")]
    assert "ci_health" in ci


def test_extract_subject_strips_intent_words():
    assert extract_subject("who owns the auth tokens module") == "auth tokens module"


def test_needs_clarification():
    assert needs_clarification("what about it?") is True
    assert needs_clarification("who owns auth") is False


# --- agent end to end (fake chat, corpus) ----------------------------------

def _agent():
    session = ephemeral_corpus_session()
    embedder = build_embedding_client("fake")
    store = InMemoryVectorStore()
    build_index(session, "acme/payments", embedder, store)
    retriever = HybridRetriever(store, embedder)
    return build_agent(session, "acme/payments", FakeChatClient(), retriever,
                       team="PAY", as_of=AS_OF)


def test_agent_answers_ownership_question_with_citations():
    answer = _agent().ask("who owns the auth tokens module")
    assert answer.abstained is False
    assert answer.clarifying_question is None
    assert answer.answer
    assert "metric:auth/tokens.py" in answer.citations
    assert any(t.tool == "ownership" for t in answer.plan)
    # Nothing cited that wasn't gathered as evidence.
    assert set(answer.citations) <= {e.ref for e in answer.evidence}


def test_agent_multi_hop_plan():
    answer = _agent().ask(
        "is the payments project at risk and who owns the risky module?"
    )
    tools = {t.tool for t in answer.plan}
    assert {"delivery", "ownership", "retrieval"} <= tools
    assert answer.abstained is False


def test_agent_abstains_on_unanswerable_question():
    answer = _agent().ask("what is the meaning of life")
    assert answer.abstained is True
    assert answer.answer is None


def test_agent_clarifies_on_vague_question():
    answer = _agent().ask("what about it?")
    assert answer.clarifying_question is not None
    assert answer.abstained is False and answer.answer is None
