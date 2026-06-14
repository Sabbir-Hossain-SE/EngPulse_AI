"""Sub-step 4.2 — RAG core: embeddings, store, chunking, hybrid retrieval."""

from __future__ import annotations

from engpulse.eval.harness import ephemeral_corpus_session
from engpulse.llm import FakeEmbeddingClient, cosine
from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_documents, build_index
from engpulse.rag.chunk import chunk_text
from engpulse.rag.store import Chunk


# --- embeddings ------------------------------------------------------------

def test_fake_embeddings_are_deterministic_and_meaningful():
    e = FakeEmbeddingClient()
    a1 = e.embed(["auth token refresh"])[0]
    a2 = e.embed(["auth token refresh"])[0]
    assert a1 == a2                              # deterministic
    assert round(cosine(a1, a2), 6) == 1.0       # identical text → cosine 1
    related = e.embed(["auth token parsing"])[0]
    unrelated = e.embed(["payment retry backoff"])[0]
    assert cosine(a1, related) > cosine(a1, unrelated)  # shared tokens rank higher


def test_chunk_text_splits_long_text():
    short = chunk_text("hello world")
    assert short == ["hello world"]
    long = chunk_text("x" * 2000, max_chars=800, overlap=100)
    assert len(long) >= 3
    assert all(len(c) <= 800 for c in long)


# --- in-memory store -------------------------------------------------------

def test_in_memory_store_vector_and_keyword():
    store = InMemoryVectorStore()
    embedder = FakeEmbeddingClient()
    chunks = [
        Chunk("c1", "commit", "sha1", "refactor auth token parsing"),
        Chunk("c2", "commit", "sha2", "add payment retry with backoff"),
    ]
    store.add(chunks, embedder.embed([c.text for c in chunks]))

    q = embedder.embed(["auth token"])[0]
    top_vec = store.search_vector(q, 1)[0][0]
    assert top_vec.chunk_id == "c1"

    kw = store.search_keyword("retry backoff", 5)
    assert kw[0][0].chunk_id == "c2"


# --- documents + hybrid retrieval over the corpus --------------------------

def test_build_documents_covers_all_kinds():
    session = ephemeral_corpus_session()
    docs = build_documents(session, "acme/payments")
    kinds = {d.kind for d in docs}
    assert {"pr", "issue", "commit", "ownership"} <= kinds
    # The ownership doc for the SPOF module exists.
    assert any(d.kind == "ownership" and d.ref == "auth/tokens.py" for d in docs)


def _corpus_retriever():
    session = ephemeral_corpus_session()
    embedder = FakeEmbeddingClient()
    store = InMemoryVectorStore()
    build_index(session, "acme/payments", embedder, store)
    return HybridRetriever(store, embedder)


def test_semantic_query_finds_owner_evidence():
    retriever = _corpus_retriever()
    results = retriever.retrieve("who owns the auth tokens module", k=5)
    refs = [r.ref for r in results]
    assert "auth/tokens.py" in refs


def test_keyword_query_finds_exact_identifier():
    # An exact issue key should be retrievable even though it is a rare token.
    retriever = _corpus_retriever()
    results = retriever.retrieve("PAY-20", k=5)
    refs = [r.ref for r in results]
    assert "PAY-20" in refs


def test_retrieval_is_deterministic():
    r1 = _corpus_retriever().retrieve("payment retry backoff", k=3)
    r2 = _corpus_retriever().retrieve("payment retry backoff", k=3)
    assert [r.ref for r in r1] == [r.ref for r in r2]
