"""Model-agnostic LLM seam (Ollama, OpenAI-compatible) + a deterministic fake.

Embeddings live here now; the chat client arrives with grounded synthesis (4.3).
Everything is reached via a base URL + model name in config, so the provider is
swappable without code changes.
"""

from engpulse.llm.chat import (
    ChatClient,
    FakeChatClient,
    OllamaChatClient,
    ScriptedChatClient,
    build_chat_client,
)
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
    "ChatClient",
    "OllamaChatClient",
    "FakeChatClient",
    "ScriptedChatClient",
    "build_chat_client",
]
