"""Worker-side sync job execution: claim a queued job, run it, land it in a
terminal state. No FastAPI request in scope here, so this talks to
public.sync_jobs directly (raw SQL, same convention as tenancy/registry.py)
and to a tenant schema via tenant_session(user_id).
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from app.connectors.s3 import S3Connector
from app.core.db import SessionLocal
from app.core.security import decrypt_json
from app.domain.models import Datasource, Directory
from app.tenancy.registry import tenant_session

POLL_INTERVAL_SECONDS = 1


class SyncError(Exception):
    pass


def claim_next_queued_job() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID] | None:
    """SELECT ... FOR UPDATE SKIP LOCKED + transition to running, one short
    transaction. Runs on a plain session: the worker doesn't know which
    tenant a job belongs to until it reads user_id off the claimed row."""
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT id, user_id, directory_id FROM public.sync_jobs
                WHERE state = 'queued'
                ORDER BY queued_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
        ).first()
        if row is None:
            db.commit()
            return None

        db.execute(
            text("UPDATE public.sync_jobs SET state = 'running', started_at = now() WHERE id = :id"),
            {"id": row.id},
        )
        db.commit()
        return row.id, row.user_id, row.directory_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_sync(job_id: uuid.UUID, user_id: uuid.UUID, directory_id: uuid.UUID) -> None:
    try:
        with tenant_session(user_id) as db:
            directory = db.get(Directory, directory_id)
            if directory is None:
                raise SyncError("directory no longer exists")

            datasource = db.get(Datasource, directory.datasource_id)
            config = decrypt_json(datasource.config_encrypted)
            connector = S3Connector(**config)
            objects = connector.list_objects(directory.prefix)

            stats = json.dumps({"scanned": len(objects)})
            db.execute(
                text(
                    """
                    UPDATE public.sync_jobs
                    SET state = 'succeeded', stats = CAST(:stats AS jsonb), finished_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "stats": stats},
            )
    except Exception as exc:
        _mark_job_failed(job_id, str(exc))


def _mark_job_failed(job_id: uuid.UUID, message: str) -> None:
    """Fresh session: the tenant_session that raised has already rolled back
    and closed by the time we get here."""
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                UPDATE public.sync_jobs
                SET state = 'failed', stats = CAST(:stats AS jsonb), finished_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "stats": json.dumps({"error": message})},
        )
        db.commit()
    finally:
        db.close()
