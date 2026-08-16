from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Document
from app.domain.refcount import is_live_clause, release_content_if_orphaned
from app.tenancy.registry import get_tenant_db

router = APIRouter(tags=["documents"])


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
