"""Vector stores behind one protocol.

* ``InMemoryVectorStore`` — embeddings held in process; cosine + token-overlap
  keyword search in pure Python. Used by tests and the offline RAG demo.
* ``PgVectorStore`` — embeddings in a pgvector column with ``<=>`` cosine search
  and ILIKE keyword search. The production store (needs Postgres + pgvector).

Both return ``(Chunk, score)`` lists so the retriever is store-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from engpulse.llm.embeddings import cosine, tokenize


@dataclass
class Chunk:
    chunk_id: str
    kind: str
    ref: str
    text: str
    metadata: dict = field(default_factory=dict)


class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    def search_vector(
        self, query_embedding: list[float], k: int
    ) -> list[tuple[Chunk, float]]: ...

    def search_keyword(self, query: str, k: int) -> list[tuple[Chunk, float]]: ...

    def count(self) -> int: ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._embeddings: list[list[float]] = []

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self._chunks.extend(chunks)
        self._embeddings.extend(embeddings)

    def count(self) -> int:
        return len(self._chunks)

    def search_vector(
        self, query_embedding: list[float], k: int
    ) -> list[tuple[Chunk, float]]:
        scored = [
            (chunk, cosine(query_embedding, emb))
            for chunk, emb in zip(self._chunks, self._embeddings)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def search_keyword(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return []
        scored = []
        for chunk in self._chunks:
            c_tokens = set(tokenize(chunk.text))
            overlap = len(q_tokens & c_tokens)
            if overlap:
                scored.append((chunk, overlap / len(q_tokens)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


class PgVectorStore:
    """Production store: a pgvector-backed ``rag_chunks`` table.

    Created on demand (outside the SQLite-tested ORM metadata) so the core schema
    stays portable. Exercised live via the ``rag-index`` / ``rag-search`` CLI.
    """

    def __init__(self, session, dim: int, repo: str) -> None:
        self._session = session
        self._dim = dim
        self._repo = repo
        self._ensure_table()

    def _ensure_table(self) -> None:
        from sqlalchemy import text

        self._session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        self._session.execute(text(
            f"""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                chunk_id TEXT PRIMARY KEY,
                repo TEXT,
                kind TEXT,
                ref TEXT,
                text TEXT,
                metadata JSONB,
                embedding vector({self._dim})
            )
            """
        ))
        self._session.commit()

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        import json

        from sqlalchemy import text

        for chunk, emb in zip(chunks, embeddings):
            self._session.execute(
                text(
                    "INSERT INTO rag_chunks (chunk_id, repo, kind, ref, text, metadata, embedding) "
                    "VALUES (:id, :repo, :kind, :ref, :text, :meta, :emb) "
                    "ON CONFLICT (chunk_id) DO UPDATE SET "
                    "text = EXCLUDED.text, embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata"
                ),
                {"id": chunk.chunk_id, "repo": self._repo, "kind": chunk.kind,
                 "ref": chunk.ref, "text": chunk.text,
                 "meta": json.dumps(chunk.metadata), "emb": str(emb)},
            )
        self._session.commit()

    def count(self) -> int:
        from sqlalchemy import text

        return self._session.execute(
            text("SELECT count(*) FROM rag_chunks WHERE repo = :repo"),
            {"repo": self._repo},
        ).scalar_one()

    def _row_to_chunk(self, row) -> Chunk:
        return Chunk(chunk_id=row.chunk_id, kind=row.kind, ref=row.ref,
                     text=row.text, metadata=row.metadata or {})

    def search_vector(
        self, query_embedding: list[float], k: int
    ) -> list[tuple[Chunk, float]]:
        from sqlalchemy import text

        rows = self._session.execute(
            text(
                "SELECT chunk_id, kind, ref, text, metadata, "
                "1 - (embedding <=> :q) AS score FROM rag_chunks "
                "WHERE repo = :repo ORDER BY embedding <=> :q LIMIT :k"
            ),
            {"q": str(query_embedding), "repo": self._repo, "k": k},
        ).all()
        return [(self._row_to_chunk(r), float(r.score)) for r in rows]

    def search_keyword(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        from sqlalchemy import text

        rows = self._session.execute(
            text(
                "SELECT chunk_id, kind, ref, text, metadata, "
                "ts_rank(to_tsvector('english', text), plainto_tsquery('english', :q)) AS score "
                "FROM rag_chunks WHERE repo = :repo "
                "AND to_tsvector('english', text) @@ plainto_tsquery('english', :q) "
                "ORDER BY score DESC LIMIT :k"
            ),
            {"q": query, "repo": self._repo, "k": k},
        ).all()
        return [(self._row_to_chunk(r), float(r.score)) for r in rows]
