"""Tracing wrappers so every LLM call emits a span (no silent calls)."""

from __future__ import annotations

from engpulse.llm.chat import ChatClient
from engpulse.llm.embeddings import EmbeddingClient
from engpulse.obs import get_tracer


class TracedChatClient:
    def __init__(self, inner: ChatClient) -> None:
        self._inner = inner

    def complete(self, messages: list[dict]) -> str:
        with get_tracer().span("llm.chat", n_messages=len(messages)) as s:
            out = self._inner.complete(messages)
            s.output = out[:500]
            return out


class TracedEmbeddingClient:
    def __init__(self, inner: EmbeddingClient) -> None:
        self._inner = inner

    @property
    def dim(self) -> int:
        return self._inner.dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        with get_tracer().span("llm.embed", n_texts=len(texts)) as s:
            out = self._inner.embed(texts)
            s.output = f"{len(out)} vectors"
            return out
