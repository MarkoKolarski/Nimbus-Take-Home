import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.db import SessionLocal
from app.domain.models import Datasource
from app.tenancy.registry import tenant_session


def _user_id(db_conn, email):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        return cur.fetchone()[0]


def test_tenant_session_sets_search_path_per_user(db_conn):
    alice_id = _user_id(db_conn, "alice@nimbus.dev")
    bob_id = _user_id(db_conn, "bob@nimbus.dev")

    with tenant_session(alice_id) as db:
        assert "tenant_alice" in db.execute(text("SHOW search_path")).scalar()

    with tenant_session(bob_id) as db:
        assert "tenant_bob" in db.execute(text("SHOW search_path")).scalar()


def test_tenant_session_isolates_rows_by_schema(db_conn):
    """Same ORM model, same unqualified table name — proves the two tenants
    resolve to physically separate tables, not just a different search_path
    string."""
    alice_id = _user_id(db_conn, "alice@nimbus.dev")
    bob_id = _user_id(db_conn, "bob@nimbus.dev")

    with tenant_session(alice_id) as db:
        ds = Datasource(kind="s3", name="isolation-test", config_encrypted="x")
        db.add(ds)
        db.flush()
        ds_id = ds.id

    try:
        with tenant_session(bob_id) as db:
            assert db.get(Datasource, ds_id) is None

        with tenant_session(alice_id) as db:
            assert db.get(Datasource, ds_id) is not None
    finally:
        with tenant_session(alice_id) as db:
            row = db.get(Datasource, ds_id)
            if row is not None:
                db.delete(row)


def test_unqualified_query_without_search_path_sees_no_tenant_table():
    """without search_path set, an unqualified query can't see any tenant table
    isolation holds even if a code path forgets to scope its session."""
    db = SessionLocal()
    try:
        with pytest.raises(ProgrammingError):
            db.execute(text("SELECT * FROM datasources"))
    finally:
        db.rollback()
        db.close()
