"""Sub-step 4.3 — grounded synthesis: schema enforcement, grounding, abstention."""

from __future__ import annotations

import json

import pytest

from engpulse.eval.harness import ephemeral_corpus_session
from engpulse.llm import FakeChatClient, ScriptedChatClient, build_embedding_client
from engpulse.metrics import compute_knowledge_risk
from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_index
from engpulse.synth import EvidenceItem, synthesize_for_flag, synthesize_insight
from engpulse.synth.grounded import (
    GeneratedInsight,
    SynthesisError,
    check_grounding,
    generate_structured,
)

VALID = json.dumps({
    "summary": "s", "likely_cause": "c", "recommended_action": "a",
    "claims": [], "confidence": 0.5,
})


# --- schema enforcement / retry-repair ------------------------------------

def test_generate_repairs_after_invalid_json():
    chat = ScriptedChatClient(["not json at all", VALID])
    result = generate_structured(chat, [{"role": "user", "content": "x"}])
    assert isinstance(result, GeneratedInsight)
    assert chat.calls == 2  # repaired on the second attempt


def test_generate_gives_up_after_max_retries():
    chat = ScriptedChatClient(["bad", "bad", "bad", "bad"])
    with pytest.raises(SynthesisError):
        generate_structured(chat, [{"role": "user", "content": "x"}], max_retries=2)
    assert chat.calls == 3  # initial + 2 retries


# --- hallucination check ---------------------------------------------------

def test_check_grounding_drops_unsupported_claims():
    gen = GeneratedInsight(
        summary="s", likely_cause="c", recommended_action="a", confidence=0.9,
        claims=[
            {"text": "real", "evidence_refs": ["PR#1"]},
            {"text": "made up", "evidence_refs": ["PR#999"]},
            {"text": "uncited", "evidence_refs": []},
        ],
    )
    grounded, dropped = check_grounding(gen, valid_refs={"PR#1"})
    assert [c.text for c in grounded] == ["real"]
    assert len(dropped) == 2


# --- abstention ------------------------------------------------------------

def test_abstains_on_insufficient_evidence():
    insight = synthesize_insight("x", "subj", "high", [], FakeChatClient())
    assert insight.abstained and insight.abstention_reason == "insufficient evidence"


def test_abstains_when_all_claims_ungrounded():
    evidence = [EvidenceItem(ref="metric:x", kind="metric", text="fact")]
    bogus = json.dumps({
        "summary": "s", "likely_cause": "c", "recommended_action": "a",
        "claims": [{"text": "hallucination", "evidence_refs": ["nope"]}],
        "confidence": 0.9,
    })
    insight = synthesize_insight("x", "subj", "high", evidence, ScriptedChatClient([bogus]))
    assert insight.abstained and insight.abstention_reason == "no grounded claims"


# --- happy path: severity from the flag, claims grounded -------------------

def test_synthesizes_grounded_insight_and_keeps_flag_severity():
    evidence = [
        EvidenceItem(ref="metric:auth/tokens.py", kind="metric", text="owned by dave"),
        EvidenceItem(ref="auth/tokens.py", kind="ownership", text="SPOF module"),
    ]
    insight = synthesize_insight(
        "single_point_of_failure", "auth/tokens.py", "high", evidence, FakeChatClient()
    )
    assert insight.abstained is False
    assert insight.severity == "high"            # from the flag, not the model
    assert insight.confidence > 0
    # Every citation is a real evidence ref (nothing hallucinated).
    assert set(insight.citations) <= {e.ref for e in evidence}


def test_end_to_end_synthesis_over_corpus():
    session = ephemeral_corpus_session()
    embedder = build_embedding_client("fake")
    store = InMemoryVectorStore()
    build_index(session, "acme/payments", embedder, store)
    retriever = HybridRetriever(store, embedder)

    flag = compute_knowledge_risk(session, "acme/payments").flags[0]
    metric_text = f"{flag.module} owned by {flag.evidence['owner']}"
    insight = synthesize_for_flag(
        flag.type, flag.module, flag.severity, metric_text, retriever,
        FakeChatClient(), query=f"{flag.module} ownership and risk",
    )
    assert insight.abstained is False
    assert insight.subject == "auth/tokens.py"
    assert insight.citations  # grounded in real evidence refs
    assert f"metric:{flag.module}" in {*insight.citations} or insight.citations
