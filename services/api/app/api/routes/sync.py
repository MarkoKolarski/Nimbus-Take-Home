from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.domain.models import Directory
from app.tenancy.registry import get_tenant_db

router = APIRouter(tags=["sync"])

_SELECT_JOB_COLUMNS = (
    "id, directory_id, state, stats, error_count, queued_at, started_at, finished_at, attempt"
)


class SyncJobOut(BaseModel):
    id: str
    directory_id: str
    state: str
    stats: dict
    error_count: int
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int


def _row_to_out(row) -> SyncJobOut:
    return SyncJobOut(
        id=str(row.id),
        directory_id=str(row.directory_id),
        state=row.state,
        stats=row.stats,
        error_count=row.error_count,
        queued_at=row.queued_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        attempt=row.attempt,
    )


def _get_directory_or_404(db: Session, directory_id: uuid.UUID) -> Directory:
    directory = db.get(Directory, directory_id)
    if directory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="directory not found")
    return directory


@router.post("/directories/{directory_id}/sync", response_model=SyncJobOut)
def enqueue_sync(
    directory_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: CurrentUser = Depends(get_current_user),
) -> SyncJobOut:
    _get_directory_or_404(db, directory_id)

    try:
        row = db.execute(
            text(
                f"""
                INSERT INTO public.sync_jobs (user_id, directory_id, state)
                VALUES (:user_id, :directory_id, 'queued')
                RETURNING {_SELECT_JOB_COLUMNS}
                """
            ),
            {"user_id": user.id, "directory_id": directory_id},
        ).first()
    except IntegrityError:
        db.rollback()
        existing = db.execute(
            text(
                f"""
                SELECT {_SELECT_JOB_COLUMNS} FROM public.sync_jobs
                WHERE directory_id = :directory_id AND state IN ('queued', 'running')
                ORDER BY queued_at DESC LIMIT 1
                """
            ),
            {"directory_id": directory_id},
        ).first()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_row_to_out(existing).model_dump(mode="json"))

    return _row_to_out(row)


@router.get("/directories/{directory_id}/sync", response_model=SyncJobOut)
def get_sync_status(
    directory_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
) -> SyncJobOut:
    _get_directory_or_404(db, directory_id)

    row = db.execute(
        text(
            f"""
            SELECT {_SELECT_JOB_COLUMNS} FROM public.sync_jobs
            WHERE directory_id = :directory_id
            ORDER BY queued_at DESC LIMIT 1
            """
        ),
        {"directory_id": directory_id},
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no sync job for this directory yet")

    return _row_to_out(row)
