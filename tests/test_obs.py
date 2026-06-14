"""Sub-step 7.2 — tracing (no silent LLM calls) and SSE streaming for /ask."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from engpulse.agent import build_agent
from engpulse.api.deps import get_session
from engpulse.api.main import app
from engpulse.api.services import clear_caches
from engpulse.eval.harness import ephemeral_corpus_session
from engpulse.llm import build_chat_client, build_embedding_client
from engpulse.obs import NoOpTracer, RecordingTracer, set_tracer
from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_index

AS_OF = datetime(2026, 6, 14, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_tracer():
    yield
    set_tracer(NoOpTracer())


def test_chat_and_embed_calls_are_traced():
    rec = RecordingTracer()
    set_tracer(rec)
    build_chat_client("fake").complete([{"role": "user", "content": "hi"}])
    build_embedding_client("fake").embed(["hello world"])
    assert "llm.chat" in rec.names()
    assert "llm.embed" in rec.names()


def test_agent_ask_traces_the_whole_pipeline():
    rec = RecordingTracer()
    set_tracer(rec)

    session = ephemeral_corpus_session()
    embedder = build_embedding_client("fake")
    store = InMemoryVectorStore()
    build_index(session, "acme/payments", embedder, store)
    agent = build_agent(session, "acme/payments", build_chat_client("fake"),
                        HybridRetriever(store, embedder), team="PAY", as_of=AS_OF)

    agent.ask("who owns the auth tokens module")
    names = rec.names()
    assert "agent.ask" in names
    assert any(n.startswith("tool.") for n in names)
    assert "llm.chat" in names  # the grounded-answer call


def test_ask_stream_emits_sse_events():
    session = ephemeral_corpus_session()
    clear_caches()
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        resp = client.post("/ask/stream", json={
            "question": "who owns the auth tokens module",
            "repo": "acme/payments", "team": "PAY", "as_of": "2026-06-14"})
        assert resp.status_code == 200
        body = resp.text
        assert "event: plan" in body
        assert "event: tool" in body
        assert "event: final" in body
        assert "metric:auth/tokens.py" in body
    finally:
        app.dependency_overrides.clear()
        clear_caches()
