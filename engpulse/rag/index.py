"""Index orchestration: documents → chunks → embeddings → store."""

from __future__ import annotations

from sqlalchemy.orm import Session

from engpulse.llm.embeddings import EmbeddingClient
from engpulse.rag.chunk import chunk_documents
from engpulse.rag.documents import build_documents
from engpulse.rag.store import Chunk, VectorStore


def build_index(
    session: Session,
    repo_full_name: str,
    embedder: EmbeddingClient,
    store: VectorStore,
    max_chars: int = 800,
) -> int:
    """Build documents for a repo, embed their chunks, and load the store.

    Returns the number of chunks indexed.
    """

    documents = build_documents(session, repo_full_name)
    doc_chunks = chunk_documents(documents, max_chars=max_chars)
    if not doc_chunks:
        return 0

    chunks = [
        Chunk(chunk_id=dc.chunk_id, kind=dc.kind, ref=dc.ref,
              text=dc.text, metadata=dc.metadata)
        for dc in doc_chunks
    ]
    embeddings = embedder.embed([c.text for c in chunks])
    store.add(chunks, embeddings)
    return len(chunks)
