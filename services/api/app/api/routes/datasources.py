from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.s3 import S3Connector
from app.core.security import decrypt_json, encrypt_json
from app.domain.models import Datasource
from app.tenancy.registry import get_tenant_db

router = APIRouter(prefix="/datasources", tags=["datasources"])


class S3ConnectionConfig(BaseModel):
    endpoint_url: str
    bucket_name: str
    access_key_id: str
    secret_access_key: str
    region_name: str = "us-east-1"


class DatasourceCreate(BaseModel):
    kind: Literal["s3"]
    name: str
    config: S3ConnectionConfig


class DatasourceOut(BaseModel):
    id: str
    kind: str
    name: str
    created_at: datetime


def _to_out(ds: Datasource) -> DatasourceOut:
    return DatasourceOut(id=str(ds.id), kind=ds.kind, name=ds.name, created_at=ds.created_at)


@router.post("", response_model=DatasourceOut)
def create_datasource(body: DatasourceCreate, db: Session = Depends(get_tenant_db)) -> DatasourceOut:
    ds = Datasource(
        kind=body.kind,
        name=body.name,
        config_encrypted=encrypt_json(body.config.model_dump()),
    )
    db.add(ds)
    db.flush()
    return _to_out(ds)


@router.get("", response_model=list[DatasourceOut])
def list_datasources(db: Session = Depends(get_tenant_db)) -> list[DatasourceOut]:
    rows = db.execute(select(Datasource).order_by(Datasource.created_at)).scalars().all()
    return [_to_out(ds) for ds in rows]


@router.get("/{datasource_id}/browse", response_model=list[str])
def browse_datasource(
    datasource_id: uuid.UUID,
    prefix: str = Query(default=""),
    db: Session = Depends(get_tenant_db),
) -> list[str]:
    ds = db.get(Datasource, datasource_id)
    if ds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="datasource not found")

    config = decrypt_json(ds.config_encrypted)
    connector = S3Connector(**config)
    return connector.list_prefixes(prefix)
