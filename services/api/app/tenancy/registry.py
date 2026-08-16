"""Maps an identity (user_id) to its tenant schema and scopes a Session to it.

get_current_user (app.core.security) is the only place identity originates;
this module is the only place that identity turns into a search_path. The
worker (later block) reuses tenant_session() directly with a plain user_id —
it has no FastAPI request to hang a Depends() off of.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.security import CurrentUser, get_current_user


def resolve_schema_name(db: Session, user_id: uuid.UUID) -> str:
    return db.execute(
        text("SELECT schema_name FROM public.tenants WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).scalar_one()


def set_search_path(db: Session, schema_name: str) -> None:
    """search_path is transaction-scoped (SET LOCAL); public must stay on the
    path or the vector column type stops resolving. schema_name always comes
    from public.tenants, never user input, but goes through
    psycopg.sql.Identifier anyway — the one audited quoting path, shared with
    provision_tenant()."""
    conn = db.connection()
    raw = conn.connection.dbapi_connection
    quoted = sql.Identifier(schema_name).as_string(raw)
    conn.exec_driver_sql(f"SET LOCAL search_path = {quoted}, public")


@contextmanager
def tenant_session(user_id: uuid.UUID) -> Iterator[Session]:
    db = SessionLocal()
    try:
        schema_name = resolve_schema_name(db, user_id)
        set_search_path(db, schema_name)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_tenant_db(user: CurrentUser = Depends(get_current_user)) -> Iterator[Session]:
    with tenant_session(user.id) as db:
        yield db
