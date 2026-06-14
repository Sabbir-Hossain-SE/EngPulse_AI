"""Hybrid retrieval: dense vectors + keyword, fused by RRF, then reranked.

Dense search catches semantic matches; keyword search catches exact identifiers
(file paths, issue keys) that embeddings can miss. Reciprocal-rank fusion merges
the two ranked lists without needing comparable score scales, and the reranker
orders the fused candidates for final precision.
"""

from __future__ import annotations

from dataclasses import dataclass

from engpulse.llm.embeddings import EmbeddingClient
from engpulse.rag.rerank import LexicalReranker, Reranker
from engpulse.rag.store import Chunk, VectorStore


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float

    @property
    def ref(self) -> str:
        return self.chunk.ref


def _rrf(ranked_lists: list[list[Chunk]], k_rrf: int = 60) -> dict[str, float]:
    """Reciprocal-rank fusion over several ranked candidate lists."""

    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (
                k_rrf + rank + 1
            )
    return scores


class HybridRetriever:
    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingClient,
        reranker: Reranker | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._reranker = reranker or LexicalReranker()

    def retrieve(
        self, query: str, k: int = 5, candidate_k: int = 20, rerank: bool = True
    ) -> list[RetrievedChunk]:
        q_emb = self._embedder.embed([query])[0]
        vec_hits = self._store.search_vector(q_emb, candidate_k)
        kw_hits = self._store.search_keyword(query, candidate_k)

        by_id: dict[str, Chunk] = {}
        for chunk, _ in vec_hits + kw_hits:
            by_id[chunk.chunk_id] = chunk

        fused = _rrf([[c for c, _ in vec_hits], [c for c, _ in kw_hits]])
        candidates = [by_id[cid] for cid in fused]

        if rerank and candidates:
            reranked = self._reranker.rerank(query, candidates)
            # Blend RRF and reranker score so neither dominates.
            results = [
                RetrievedChunk(chunk=chunk, score=round(fused[chunk.chunk_id] + rscore, 4))
                for chunk, rscore in reranked
            ]
        else:
            results = [
                RetrievedChunk(chunk=by_id[cid], score=round(score, 4))
                for cid, score in sorted(fused.items(), key=lambda x: x[1], reverse=True)
            ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]
