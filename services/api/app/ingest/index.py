"""Per-object ingest: three dedup layers, commit boundary is the
caller's (sync/runner.py commits once per object for crash recovery).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import Connector, ObjectMeta
from app.domain.models import Chunk, Content, Datasource, Directory, Document
from app.domain.refcount import release_content_if_orphaned
from app.ingest.chunk import chunk_text
from app.ingest.embed import Embedder
from app.ingest.extract import extract_text
from app.ingest.hash import sha256_bytes

IngestOutcome = Literal["unchanged", "indexed", "deduped"]


def _find_document(db: Session, directory_id, source_key: str) -> Document | None:
    return db.execute(
        select(Document).where(Document.directory_id == directory_id, Document.source_key == source_key)
    ).scalar_one_or_none()


def ingest_object(
    db: Session,
    connector: Connector,
    directory: Directory,
    datasource: Datasource,
    obj: ObjectMeta,
    embedder: Embedder,
) -> IngestOutcome:
    existing = _find_document(db, directory.id, obj.key)

    # Layer 1: (source_key, etag, size) unchanged to skip download entirely.
    if existing is not None and existing.remote_etag == obj.etag and existing.remote_size == obj.size:
        return "unchanged"

    raw = connector.get_object_bytes(obj.key)
    content_hash = sha256_bytes(raw)
    old_content_hash = existing.content_hash if existing else None

    # Layer 2: content already indexed under this hash -> skip
    content_row = db.get(Content, content_hash)
    if content_row is None:
        filename = Path(obj.key).name
        text, mime = extract_text(filename, raw)
        pieces = chunk_text(text)
        vectors = embedder.embed(pieces) if pieces else []

        db.add(
            Content(
                content_hash=content_hash,
                byte_size=len(raw),
                mime=mime,
                text_len=len(text),
                chunk_count=len(pieces),
            )
        )
        # No relationship() between Content and Chunk (raw FK only), so the
        # ORM wont auto-order these two inserts, flush contents first or
        # the chunks insert violates chunks_content_hash_fkey.
        db.flush()
        for ord_, (piece, vector) in enumerate(zip(pieces, vectors)):
            db.add(Chunk(content_hash=content_hash, ord=ord_, text_=piece, token_count=len(piece) // 4, embedding=vector))
        outcome: IngestOutcome = "indexed"
    else:
        outcome = "deduped"

    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.content_hash = content_hash
        existing.remote_etag = obj.etag
        existing.remote_size = obj.size
        existing.remote_modified_at = obj.last_modified
        existing.state = "indexed"
        existing.error = None
        existing.indexed_at = now

        # Content actually changed at this path to new file, on purpose
        existing.removed_at = None
    else:
        db.add(
            Document(
                directory_id=directory.id,
                datasource_id=datasource.id,
                source_key=obj.key,
                filename=Path(obj.key).name,
                content_hash=content_hash,
                remote_etag=obj.etag,
                remote_size=obj.size,
                remote_modified_at=obj.last_modified,
                state="indexed",
                indexed_at=now,
            )
        )

    db.flush()

    if old_content_hash is not None and old_content_hash != content_hash:
        release_content_if_orphaned(db, old_content_hash)

    return outcome
