from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Directory, Document
from app.domain.refcount import is_live_clause, release_content_if_orphaned
from app.tenancy.registry import get_tenant_db

router = APIRouter(tags=["documents"])


class DocumentOut(BaseModel):
    id: str
    filename: str
    source_key: str
    state: str
    error: str | None
    indexed_at: datetime | None


def _to_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=str(document.id),
        filename=document.filename,
        source_key=document.source_key,
        state=document.state,
        error=document.error,
        indexed_at=document.indexed_at,
    )


@router.get("/directories/{directory_id}/documents", response_model=list[DocumentOut])
def list_documents(directory_id: uuid.UUID, db: Session = Depends(get_tenant_db)) -> list[DocumentOut]:
    if db.get(Directory, directory_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="directory not found")

    # removed_at IS NULL only, not is_live_clause(): this is the one screen
    # that must also show non-indexed states (failed, deleted_at_source),
    # is_live_clause() would hide those from the user.
    rows = db.execute(
        select(Document)
        .where(Document.directory_id == directory_id, Document.removed_at.is_(None))
        .order_by(Document.filename)
    ).scalars().all()
    return [_to_out(d) for d in rows]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_tenant_db)) -> None:
    # is_live_clause() in the query itself, not a Python re-check after
    # loading: missing, cross-tenant, and already-removed all collapse to
    # the same 404 without a second implementation of the predicate.
    document = db.execute(
        select(Document).where(Document.id == document_id, is_live_clause())
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")

    old_content_hash = document.content_hash
    document.removed_at = datetime.now(timezone.utc)
    db.flush()

    if old_content_hash is not None:
        release_content_if_orphaned(db, old_content_hash)
