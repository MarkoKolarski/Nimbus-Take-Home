import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.domain.models import Datasource, Directory, Document
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


def _register_directory(client: TestClient, datasource_id: str, prefix: str) -> dict:
    resp = client.post(f"/datasources/{datasource_id}/directories", json={"prefix": prefix})
    assert resp.status_code == 200
    return resp.json()


def _sync_and_wait(client: TestClient, directory_id: str, timeout: float = 20.0) -> dict:
    resp = client.post(f"/directories/{directory_id}/sync")
    assert resp.status_code == 200
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/directories/{directory_id}/sync").json()
        if job["state"] in ("succeeded", "failed"):
            return job
        time.sleep(0.3)
    raise TimeoutError("sync job did not reach a terminal state in time")


def _cleanup(db_conn, email: str, datasource_id: str, directory_ids: list[str]) -> None:
    with db_conn.cursor() as cur:
        for directory_id in directory_ids:
            cur.execute("DELETE FROM sync_jobs WHERE directory_id = %s", (uuid.UUID(directory_id),))
    db_conn.commit()

    with tenant_session(_user_id(db_conn, email)) as db:
        for directory in db.execute(
            select(Directory).where(Directory.datasource_id == uuid.UUID(datasource_id))
        ).scalars():
            db.execute(delete(Document).where(Document.directory_id == directory.id))
            db.delete(directory)
        db.flush()
        row = db.get(Datasource, uuid.UUID(datasource_id))
        if row is not None:
            db.delete(row)


def test_list_documents_after_sync(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "documents-list")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")
        assert _sync_and_wait(alice, directory["id"])["state"] == "succeeded"

        resp = alice.get(f"/directories/{directory['id']}/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert docs, "expected at least one document"
        assert all(d["state"] == "indexed" for d in docs)
        filenames = {d["filename"] for d in docs}
        assert "msa.md" in filenames
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], [directory["id"]] if directory else [])


def test_removed_document_excluded_from_list(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "documents-list-removed")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")
        assert _sync_and_wait(alice, directory["id"])["state"] == "succeeded"

        docs = alice.get(f"/directories/{directory['id']}/documents").json()
        doc_id = next(d["id"] for d in docs if d["filename"] == "msa.md")

        assert alice.delete(f"/documents/{doc_id}").status_code == 204

        docs_after = alice.get(f"/directories/{directory['id']}/documents").json()
        assert doc_id not in {d["id"] for d in docs_after}
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], [directory["id"]] if directory else [])


def test_list_documents_unknown_directory_returns_404(db_conn):
    alice = _client_as("alice@nimbus.dev")
    resp = alice.get(f"/directories/{uuid.uuid4()}/documents")
    assert resp.status_code == 404


def test_list_documents_someone_elses_directory_returns_404(db_conn):
    alice = _client_as("alice@nimbus.dev")
    bob = _client_as("bob@nimbus.dev")
    ds = _create_datasource(alice, "documents-list-isolation")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")
        assert _sync_and_wait(alice, directory["id"])["state"] == "succeeded"

        resp = bob.get(f"/directories/{directory['id']}/documents")
        assert resp.status_code == 404
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], [directory["id"]] if directory else [])
