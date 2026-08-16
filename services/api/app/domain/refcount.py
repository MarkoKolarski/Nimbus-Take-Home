"""Single definition of the "live document" predicate:
removed_at IS NULL AND state = 'indexed'. Used by layer-3 dedup here, and
later by DELETE /documents/{id}, directory cascade delete, and the v1.2
known_keys diff — never inline a different version of this check.
"""
from __future__ import annotations

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.orm import Session

from app.domain.models import Chunk, Content, Document


def is_live_clause() -> ColumnElement[bool]:
    return Document.removed_at.is_(None) & (Document.state == "indexed")


def release_content_if_orphaned(db: Session, content_hash: str) -> None:
    """Delete chunks + contents for content_hash if no live document
    references it anymore. chunks and contents share a lifecycle, always
    delete chunks first, contents second."""
    live_count = db.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.content_hash == content_hash, is_live_clause())
    ).scalar_one()

    if live_count == 0:
        db.execute(delete(Chunk).where(Chunk.content_hash == content_hash))
        db.execute(delete(Content).where(Content.content_hash == content_hash))
