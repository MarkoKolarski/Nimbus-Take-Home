"""Worker-side sync job execution: claim a queued job, run it, land it in a
terminal state. No FastAPI request in scope here, so this talks to
public.sync_jobs directly (raw SQL, same convention as tenancy/registry.py)
and manages its own tenant-scoped session (see run_sync for why it can't use
tenant_session()'s single-commit-at-the-end shape).
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import exists, select, text

from app.connectors.s3 import S3Connector
from app.core.db import SessionLocal
from app.core.security import decrypt_json
from app.domain.models import Datasource, Directory
from app.ingest.embed import get_embedder
from app.ingest.index import ingest_object
from app.tenancy.registry import resolve_schema_name, set_search_path

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
    """Commits once per object, not once for the whole directory: 
    requires a worker that dies mid-sync to resume rather than restart.
    SET LOCAL search_path only lasts the transaction it was set in, so it
    must be re-armed after every commit or the next unqualified query
    (documents/contents/chunks) silently resolves against the wrong schema.
    """
    db = SessionLocal()
    try:
        schema_name = resolve_schema_name(db, user_id)
        set_search_path(db, schema_name)

        directory = db.get(Directory, directory_id)
        if directory is None:
            raise SyncError("directory no longer exists")

        datasource = db.get(Datasource, directory.datasource_id)
        config = decrypt_json(datasource.config_encrypted)
        connector = S3Connector(**config)
        objects = connector.list_objects(directory.prefix)
        embedder = get_embedder()

        stats = {"scanned": len(objects), "unchanged": 0, "downloaded": 0, "indexed": 0, "deduped": 0}

        for obj in objects:
            # Concurrent DELETE /directories/{id} can land mid-loop; recheck
            # every iteration so we don't resurrect content for a
            # directory that's gone. Once gone it stays gone, so break
            # rather than skip-and-continue.
            still_exists = db.execute(select(exists().where(Directory.id == directory_id))).scalar_one()
            if not still_exists:
                break

            outcome = ingest_object(db, connector, directory, datasource, obj, embedder)
            stats[outcome] += 1
            if outcome != "unchanged":
                stats["downloaded"] += 1
            db.commit()
            set_search_path(db, schema_name)

        db.execute(
            text(
                """
                UPDATE public.sync_jobs
                SET state = 'succeeded', stats = CAST(:stats AS jsonb), finished_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "stats": json.dumps(stats)},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        _mark_job_failed(job_id, str(exc))
    finally:
        db.close()


def _mark_job_failed(job_id: uuid.UUID, message: str) -> None:
    """Fresh session: the session that raised has already rolled back by the
    time we get here, and may be mid-way through a re-armed search_path."""
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
