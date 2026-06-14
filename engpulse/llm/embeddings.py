"""Embedding clients behind one protocol.

* ``OllamaEmbeddingClient`` — live, via the OpenAI-compatible ``/embeddings``
  endpoint (e.g. ``nomic-embed-text``).
* ``FakeEmbeddingClient`` — deterministic hashed bag-of-words vectors, so
  retrieval ranking is reproducible offline (shared tokens → higher cosine).

The retriever depends only on the protocol, so live ↔ fake is a config switch.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

from engpulse.config import get_settings
from engpulse.logging import get_logger

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

# Common words ignored when judging topical relevance (not when embedding).
_STOPWORDS = {
    "the", "a", "an", "of", "and", "to", "in", "on", "at", "for", "is", "are",
    "was", "were", "be", "by", "with", "as", "it", "this", "that", "these",
    "those", "they", "them", "we", "our", "you", "i", "what", "who", "when",
    "where", "why", "how", "do", "does", "did", "about", "any", "there",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def content_tokens(text: str) -> set[str]:
    """Topical tokens (stopwords + 1-char tokens removed)."""

    return {t for t in tokenize(text) if t not in _STOPWORDS and len(t) > 1}


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


class EmbeddingClient(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbeddingClient:
    """Live embeddings via Ollama's OpenAI-compatible endpoint."""

    def __init__(
        self, base_url: str | None = None, model: str | None = None, dim: int = 768
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_embed_model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{self._base_url}/embeddings",
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        ordered = sorted(data, key=lambda d: d.get("index", 0))
        vectors = [d["embedding"] for d in ordered]
        if vectors:
            self.dim = len(vectors[0])
        return vectors


class FakeEmbeddingClient:
    """Deterministic hashed bag-of-words embeddings for offline tests/eval."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in tokenize(text):
            idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


def build_embedding_client(source: str = "fake") -> EmbeddingClient:
    if source == "ollama":
        return OllamaEmbeddingClient()
    if source == "fake":
        return FakeEmbeddingClient()
    raise ValueError(f"Unknown embedding source '{source}' (expected 'ollama' or 'fake')")
