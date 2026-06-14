"""Model-agnostic LLM seam (Ollama, OpenAI-compatible) + a deterministic fake.

Embeddings live here now; the chat client arrives with grounded synthesis (4.3).
Everything is reached via a base URL + model name in config, so the provider is
swappable without code changes.
"""

from engpulse.llm.embeddings import (
    EmbeddingClient,
    FakeEmbeddingClient,
    OllamaEmbeddingClient,
    build_embedding_client,
    cosine,
)

__all__ = [
    "EmbeddingClient",
    "OllamaEmbeddingClient",
    "FakeEmbeddingClient",
    "build_embedding_client",
    "cosine",
]
