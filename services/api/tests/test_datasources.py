import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.models import Datasource
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
    with tenant_session(_user_id(db_conn, email)) as db:
        row = db.get(Datasource, uuid.UUID(datasource_id))
        if row is not None:
            db.delete(row)


def test_create_and_list_datasource(db_conn):
    alice = _client_as("alice@nimbus.dev")
    created = _create_datasource(alice, name="create-and-list")
    try:
        assert created["kind"] == "s3"
        assert created["name"] == "create-and-list"
        assert "config" not in created

        listed = alice.get("/datasources").json()
        assert any(ds["id"] == created["id"] for ds in listed)
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", created["id"])


def test_browse_returns_real_prefixes_from_localstack(db_conn):
    alice = _client_as("alice@nimbus.dev")
    created = _create_datasource(alice, name="browse-prefixes")
    try:
        resp = alice.get(f"/datasources/{created['id']}/browse", params={"prefix": "alice/"})
        assert resp.status_code == 200
        assert {"alice/contracts/", "alice/duplicates/"} <= set(resp.json())
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", created["id"])


def test_datasource_list_does_not_leak_across_tenants(db_conn):
    alice = _client_as("alice@nimbus.dev")
    bob = _client_as("bob@nimbus.dev")
    created = _create_datasource(alice, name="isolation-list-test")
    try:
        bob_ids = {ds["id"] for ds in bob.get("/datasources").json()}
        assert created["id"] not in bob_ids
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", created["id"])


def test_browse_someone_elses_datasource_returns_404_not_403(db_conn):
    alice = _client_as("alice@nimbus.dev")
    bob = _client_as("bob@nimbus.dev")
    created = _create_datasource(alice, name="isolation-browse-test")
    try:
        resp = bob.get(f"/datasources/{created['id']}/browse")
        assert resp.status_code == 404
    finally:
        _delete_datasource(db_conn, "alice@nimbus.dev", created["id"])
