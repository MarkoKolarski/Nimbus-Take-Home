import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.domain.models import Datasource, Directory
from app.main import app
from app.seed import DEMO_PASSWORD
from app.tenancy.registry import tenant_session


def _client_as(email: str) -> TestClient:
    client = TestClient(app)
    client.post("/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    return client


def _user_id(db_conn, email):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        return cur.fetchone()[0]


def _s3_config() -> dict:
    return {
        "endpoint_url": settings.s3_endpoint_url,
        "bucket_name": settings.s3_bucket_name,
        "access_key_id": settings.aws_access_key_id,
        "secret_access_key": settings.aws_secret_access_key,
        "region_name": settings.aws_default_region,
    }


def _create_datasource(client: TestClient, name: str) -> dict:
    resp = client.post("/datasources", json={"kind": "s3", "name": name, "config": _s3_config()})
    assert resp.status_code == 200
    return resp.json()


def _delete_datasource(db_conn, email: str, datasource_id: str) -> None:
    """directories.datasource_id has no ON DELETE CASCADE, tests must clear child directories first."""
    with tenant_session(_user_id(db_conn, email)) as db:
        for directory in db.execute(
            select(Directory).where(Directory.datasource_id == uuid.UUID(datasource_id))
        ).scalars():
            db.delete(directory)
        db.flush()
        row = db.get(Datasource, uuid.UUID(datasource_id))
        if row is not None:
            db.delete(row)


def test_register_and_list_directory(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, name="dir-register-list")
    try:
        resp = alice.post(f"/datasources/{ds['id']}/directories", json={"prefix": "alice/contracts/"})
        assert resp.status_code == 200
        created = resp.json()
        assert created["datasource_id"] == ds["id"]
        assert created["prefix"] == "alice/contracts/"

        listed = alice.get(f"/datasources/{ds['id']}/directories").json()
        assert any(d["id"] == created["id"] for d in listed)
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", ds["id"])


def test_register_duplicate_prefix_returns_409(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, name="dir-duplicate")
    try:
        first = alice.post(f"/datasources/{ds['id']}/directories", json={"prefix": "alice/contracts/"})
        assert first.status_code == 200

        second = alice.post(f"/datasources/{ds['id']}/directories", json={"prefix": "alice/contracts/"})
        assert second.status_code == 409
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", ds["id"])


def test_register_directory_for_unknown_datasource_returns_404(db_conn):
    alice = _client_as("alice@nimbus.dev")
    resp = alice.post(f"/datasources/{uuid.uuid4()}/directories", json={"prefix": "x/"})
    assert resp.status_code == 404


def test_delete_directory(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, name="dir-delete")
    try:
        created = alice.post(f"/datasources/{ds['id']}/directories", json={"prefix": "alice/contracts/"}).json()

        resp = alice.delete(f"/directories/{created['id']}")
        assert resp.status_code == 204

        listed = alice.get(f"/datasources/{ds['id']}/directories").json()
        assert not any(d["id"] == created["id"] for d in listed)
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", ds["id"])


def test_directory_register_and_list_do_not_leak_across_tenants(db_conn):
    alice = _client_as("alice@nimbus.dev")
    bob = _client_as("bob@nimbus.dev")
    ds = _create_datasource(alice, name="dir-isolation")
    try:
        register_resp = bob.post(f"/datasources/{ds['id']}/directories", json={"prefix": "alice/contracts/"})
        assert register_resp.status_code == 404

        list_resp = bob.get(f"/datasources/{ds['id']}/directories")
        assert list_resp.status_code == 404
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", ds["id"])


def test_delete_someone_elses_directory_returns_404_not_403(db_conn):
    alice = _client_as("alice@nimbus.dev")
    bob = _client_as("bob@nimbus.dev")
    ds = _create_datasource(alice, name="dir-delete-isolation")
    try:
        created = alice.post(f"/datasources/{ds['id']}/directories", json={"prefix": "alice/contracts/"}).json()

        resp = bob.delete(f"/directories/{created['id']}")
        assert resp.status_code == 404

        listed = alice.get(f"/datasources/{ds['id']}/directories").json()
        assert any(d["id"] == created["id"] for d in listed)
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", ds["id"])
