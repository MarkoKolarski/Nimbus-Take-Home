"""Tenant-scoped vector search. No user_id filter anywhere here, isolation
comes from search_path (app.tenancy.registry), same as every other tenant
query. The live-document filter is the second, independent enforcement of
is_live_clause() (first is dedup layer 3, app/ingest/index.py): a removed
document's chunks must never surface as a citation even if the row is
still physically present.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Chunk, Document
from app.domain.refcount import is_live_clause


@dataclass(frozen=True)
class ChunkHit:
    content_hash: str
    text: str
    similarity: float


class VectorStore(Protocol):
    def search(self, db: Session, query_vector: list[float], k: int) -> list[ChunkHit]: ...


class PgVectorStore:
    def search(self, db: Session, query_vector: list[float], k: int) -> list[ChunkHit]:
        live_hashes = select(Document.content_hash).where(is_live_clause()).distinct()
        distance = Chunk.embedding.cosine_distance(query_vector)

        rows = db.execute(
            select(Chunk.content_hash, Chunk.text_, distance.label("distance"))
            .where(Chunk.content_hash.in_(live_hashes))
            .order_by(distance)
            .limit(k)
        ).all()

        return [
            ChunkHit(content_hash=row.content_hash, text=row.text_, similarity=1 - row.distance)
            for row in rows
        ]
