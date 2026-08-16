import time
import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.seed import DEMO_PASSWORD


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


def _poll_until_terminal(client: TestClient, directory_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/directories/{directory_id}/sync")
        job = resp.json()
        if job["state"] in ("succeeded", "failed"):
            return job
        time.sleep(0.3)
    raise TimeoutError("sync job did not reach a terminal state in time")


def _cleanup(db_conn, email: str, datasource_id: str, directory_id: str | None) -> None:
    """directories/datasources have no ON DELETE CASCADE and sync_jobs has no
    FK into a tenant schema at all, every layer is cleared by hand.
    documents FK-references directories with no cascade either, so they go first."""
    from sqlalchemy import delete, select

    from app.domain.models import Datasource, Directory, Document
    from app.tenancy.registry import tenant_session

    if directory_id is not None:
        with db_conn.cursor() as cur:
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


def test_sync_enqueues_and_worker_completes_it(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "sync-happy-path")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")

        resp = alice.post(f"/directories/{directory['id']}/sync")
        assert resp.status_code == 200
        assert resp.json()["state"] == "queued"

        job = _poll_until_terminal(alice, directory["id"])
        assert job["state"] == "succeeded"
        assert job["stats"]["scanned"] == 3
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], directory["id"] if directory else None)


def test_second_sync_click_returns_409_with_existing_job(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "sync-double-click")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")

        first = alice.post(f"/directories/{directory['id']}/sync")
        assert first.status_code == 200

        second = alice.post(f"/directories/{directory['id']}/sync")
        assert second.status_code == 409
        assert second.json()["detail"]["state"] in ("queued", "running")

        _poll_until_terminal(alice, directory["id"])
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], directory["id"] if directory else None)


def test_sync_someone_elses_directory_returns_404(db_conn):
    alice = _client_as("alice@nimbus.dev")
    bob = _client_as("bob@nimbus.dev")
    ds = _create_datasource(alice, "sync-isolation")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")

        assert bob.post(f"/directories/{directory['id']}/sync").status_code == 404
        assert bob.get(f"/directories/{directory['id']}/sync").status_code == 404
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], directory["id"] if directory else None)


def test_sync_unregistered_directory_returns_404(db_conn):
    alice = _client_as("alice@nimbus.dev")
    resp = alice.post(f"/directories/{uuid.uuid4()}/sync")
    assert resp.status_code == 404


def test_poll_before_any_sync_returns_404(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "sync-no-job-yet")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")
        resp = alice.get(f"/directories/{directory['id']}/sync")
        assert resp.status_code == 404
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], directory["id"] if directory else None)


def test_worker_marks_job_failed_when_directory_missing(db_conn):
    alice_id = _user_id(db_conn, "alice@nimbus.dev")
    fake_directory_id = uuid.uuid4()

    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sync_jobs (user_id, directory_id, state) VALUES (%s, %s, 'queued') RETURNING id",
            (alice_id, fake_directory_id),
        )
        job_id = cur.fetchone()[0]
    db_conn.commit()

    try:
        deadline = time.time() + 10.0
        state = None
        while time.time() < deadline:
            with db_conn.cursor() as cur:
                cur.execute("SELECT state FROM sync_jobs WHERE id = %s", (job_id,))
                state = cur.fetchone()[0]
            if state in ("succeeded", "failed"):
                break
            time.sleep(0.3)
        assert state == "failed"
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM sync_jobs WHERE id = %s", (job_id,))
        db_conn.commit()
