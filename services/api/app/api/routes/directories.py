from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.models import Datasource, Directory
from app.tenancy.registry import get_tenant_db

router = APIRouter(tags=["directories"])


class DirectoryCreate(BaseModel):
    prefix: str


class DirectoryOut(BaseModel):
    id: str
    datasource_id: str
    prefix: str
    created_at: datetime


def _to_out(directory: Directory) -> DirectoryOut:
    return DirectoryOut(
        id=str(directory.id),
        datasource_id=str(directory.datasource_id),
        prefix=directory.prefix,
        created_at=directory.created_at,
    )


def _get_datasource_or_404(db: Session, datasource_id: uuid.UUID) -> Datasource:
    ds = db.get(Datasource, datasource_id)
    if ds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="datasource not found")
    return ds


@router.post("/datasources/{datasource_id}/directories", response_model=DirectoryOut)
def register_directory(
    datasource_id: uuid.UUID,
    body: DirectoryCreate,
    db: Session = Depends(get_tenant_db),
) -> DirectoryOut:
    _get_datasource_or_404(db, datasource_id)

    directory = Directory(datasource_id=datasource_id, prefix=body.prefix)
    db.add(directory)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="directory already registered")
    return _to_out(directory)


@router.get("/datasources/{datasource_id}/directories", response_model=list[DirectoryOut])
def list_directories(
    datasource_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
) -> list[DirectoryOut]:
    _get_datasource_or_404(db, datasource_id)

    rows = db.execute(
        select(Directory).where(Directory.datasource_id == datasource_id).order_by(Directory.created_at)
    ).scalars().all()
    return [_to_out(d) for d in rows]


@router.delete("/directories/{directory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_directory(directory_id: uuid.UUID, db: Session = Depends(get_tenant_db)) -> None:
    directory = db.get(Directory, directory_id)
    if directory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="directory not found")
    db.delete(directory)
