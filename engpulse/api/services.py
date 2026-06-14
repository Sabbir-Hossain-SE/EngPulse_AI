"""Shared API services: a cached retriever and an agent factory.

The hybrid index is rebuilt at most once per TTL window per repo (it holds copied
chunks, so it is independent of any single request's session).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from engpulse.agent import build_agent
from engpulse.agent.agent import AskAgent
from engpulse.api.cache import TTLCache
from engpulse.config import get_settings
from engpulse.llm import build_chat_client, build_embedding_client
from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_index

_retriever_cache = TTLCache(ttl_seconds=300.0)


def get_retriever(session: Session, repo: str) -> HybridRetriever:
    cached = _retriever_cache.get(repo)
    if cached is not None:
        return cached
    embedder = build_embedding_client(get_settings().llm_source)
    store = InMemoryVectorStore()
    build_index(session, repo, embedder, store)
    retriever = HybridRetriever(store, embedder)
    _retriever_cache.set(repo, retriever)
    return retriever


def get_agent(
    session: Session, repo: str, team: str | None, as_of: datetime | None
) -> AskAgent:
    chat = build_chat_client(get_settings().llm_source)
    retriever = get_retriever(session, repo)
    return build_agent(session, repo, chat, retriever, team=team, as_of=as_of)


def clear_caches() -> None:
    _retriever_cache.clear()
