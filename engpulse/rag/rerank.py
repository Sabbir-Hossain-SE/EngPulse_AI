"""Rerankers behind one protocol (pluggable).

The default ``LexicalReranker`` reorders candidates by query/chunk token overlap
(precision-recall balanced, zero dependencies). A local cross-encoder reranker
can be dropped in later without touching the retriever — it just needs to satisfy
``rerank(query, chunks) -> [(chunk, score)]``.
"""

from __future__ import annotations

from typing import Protocol

from engpulse.llm.embeddings import tokenize
from engpulse.rag.store import Chunk


class Reranker(Protocol):
    def rerank(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]: ...


class LexicalReranker:
    """Token-overlap (Jaccard-style) reranking — light, deterministic default."""

    def rerank(self, query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
        q = set(tokenize(query))
        scored: list[tuple[Chunk, float]] = []
        for chunk in chunks:
            c = set(tokenize(chunk.text))
            union = q | c
            score = len(q & c) / len(union) if union else 0.0
            scored.append((chunk, round(score, 4)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
