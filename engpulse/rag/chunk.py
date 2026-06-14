"""Chunking: split documents into indexable units.

Most of our records (titles, messages, ownership statements) are short and stay
a single chunk; long PR bodies are split on a character budget with overlap.
Each chunk keeps a stable id and its source ref for citation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engpulse.rag.documents import Document


@dataclass
class DocChunk:
    chunk_id: str
    kind: str
    ref: str
    text: str
    metadata: dict = field(default_factory=dict)


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def chunk_documents(
    documents: list[Document], max_chars: int = 800, overlap: int = 100
) -> list[DocChunk]:
    chunks: list[DocChunk] = []
    for doc in documents:
        pieces = chunk_text(doc.text, max_chars=max_chars, overlap=overlap)
        for i, piece in enumerate(pieces):
            suffix = "" if len(pieces) == 1 else f"#{i}"
            chunks.append(DocChunk(
                chunk_id=f"{doc.doc_id}{suffix}",
                kind=doc.kind, ref=doc.ref, text=piece, metadata=dict(doc.metadata),
            ))
    return chunks
