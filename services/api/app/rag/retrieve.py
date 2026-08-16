"""Turns a question into numbered, cited sources. The threshold check on
top-1 similarity happens here, in code, before any LLM call, an empty
list means "send no context at all," not "send weak context and hope the
model notices."
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Document
from app.domain.refcount import is_live_clause
from app.ingest.embed import Embedder
from app.rag.vectorstore import VectorStore

TOP_K = 5
# Measured against bge-small-en-v1.5 on the fixture corpus: unrelated
# same-domain business docs (e.g. an onboarding guide vs. a license-fee
# question) still land ~0.50 cosine similarity — a floor from shared
# vocabulary, not relevance. 0.5 let those through; 0.55 separates them
# from genuinely on-topic hits (which scored 0.65-0.78) without rejecting
# real matches.
SIMILARITY_THRESHOLD = 0.55


@dataclass(frozen=True)
class Source:
    number: int
    content_hash: str
    text: str
    filenames: list[str]
    similarity: float


def _live_filenames(db: Session, content_hashes: set[str]) -> dict[str, list[str]]:
    if not content_hashes:
        return {}
    rows = db.execute(
        select(Document.content_hash, Document.filename)
        .where(Document.content_hash.in_(content_hashes), is_live_clause())
    ).all()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row.content_hash, [])
        if row.filename not in result[row.content_hash]:
            result[row.content_hash].append(row.filename)
    return result


def retrieve(
    db: Session,
    embedder: Embedder,
    vectorstore: VectorStore,
    question: str,
    k: int = TOP_K,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[Source]:
    query_vector = embedder.embed([question])[0]
    hits = vectorstore.search(db, query_vector, k)

    if not hits or hits[0].similarity < threshold:
        return []

    filenames_by_hash = _live_filenames(db, {hit.content_hash for hit in hits})
    return [
        Source(
            number=i + 1,
            content_hash=hit.content_hash,
            text=hit.text,
            filenames=filenames_by_hash.get(hit.content_hash, []),
            similarity=hit.similarity,
        )
        for i, hit in enumerate(hits)
    ]
