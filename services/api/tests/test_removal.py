import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.domain.models import Chunk, Content, Datasource, Directory, Document
from app.main import app
from app.seed import DEMO_PASSWORD
from app.sync import runner as sync_runner
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


def _find_document(db, directory_id: str, filename: str) -> Document:
    return db.execute(
        select(Document).where(
            Document.directory_id == uuid.UUID(directory_id),
            Document.filename == filename,
        )
    ).scalar_one()


def _content_and_chunks_exist(db, content_hash: str) -> bool:
    return db.get(Content, content_hash) is not None


def test_delete_document_releases_content_only_when_no_live_reference_remains(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "removal-refcount")
    contracts_dir = None
    duplicates_dir = None
    try:
        contracts_dir = _register_directory(alice, ds["id"], "alice/contracts/")
        assert _sync_and_wait(alice, contracts_dir["id"])["state"] == "succeeded"

        duplicates_dir = _register_directory(alice, ds["id"], "alice/duplicates/")
        assert _sync_and_wait(alice, duplicates_dir["id"])["state"] == "succeeded"

        alice_id = _user_id(db_conn, "alice@nimbus.dev")
        with tenant_session(alice_id) as db:
            msa = _find_document(db, contracts_dir["id"], "msa.md")
            msa_copy = _find_document(db, duplicates_dir["id"], "msa_copy.md")
            assert msa.content_hash == msa_copy.content_hash
            content_hash = msa.content_hash
            msa_copy_id = str(msa_copy.id)
            msa_id = str(msa.id)

        resp = alice.delete(f"/documents/{msa_copy_id}")
        assert resp.status_code == 204

        with tenant_session(alice_id) as db:
            assert _content_and_chunks_exist(db, content_hash)
            chunk_count = db.execute(
                select(func.count()).select_from(Chunk).where(Chunk.content_hash == content_hash)
            ).scalar_one()
            assert chunk_count > 0

        resp = alice.delete(f"/documents/{msa_id}")
        assert resp.status_code == 204

        with tenant_session(alice_id) as db:
            assert not _content_and_chunks_exist(db, content_hash)
            chunk_count = db.execute(
                select(func.count()).select_from(Chunk).where(Chunk.content_hash == content_hash)
            ).scalar_one()
            assert chunk_count == 0
    finally:
        dir_ids = [d["id"] for d in (contracts_dir, duplicates_dir) if d is not None]
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], dir_ids)


def test_delete_unknown_document_returns_404(db_conn):
    alice = _client_as("alice@nimbus.dev")
    resp = alice.delete(f"/documents/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_delete_someone_elses_document_returns_404_not_403(db_conn):
    alice = _client_as("alice@nimbus.dev")
    bob = _client_as("bob@nimbus.dev")
    ds = _create_datasource(alice, "removal-isolation")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")
        assert _sync_and_wait(alice, directory["id"])["state"] == "succeeded"

        alice_id = _user_id(db_conn, "alice@nimbus.dev")
        with tenant_session(alice_id) as db:
            doc = _find_document(db, directory["id"], "msa.md")
            doc_id = str(doc.id)

        resp = bob.delete(f"/documents/{doc_id}")
        assert resp.status_code == 404

        with tenant_session(alice_id) as db:
            still_there = db.get(Document, uuid.UUID(doc_id))
            assert still_there is not None
            assert still_there.removed_at is None
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], [directory["id"]] if directory else [])


def test_removed_document_does_not_reappear_on_unchanged_resync(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "removal-survives-resync")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")
        assert _sync_and_wait(alice, directory["id"])["state"] == "succeeded"

        alice_id = _user_id(db_conn, "alice@nimbus.dev")
        with tenant_session(alice_id) as db:
            doc = _find_document(db, directory["id"], "msa.md")
            doc_id = str(doc.id)

        assert alice.delete(f"/documents/{doc_id}").status_code == 204

        second = _sync_and_wait(alice, directory["id"])
        assert second["state"] == "succeeded"
        assert second["stats"]["unchanged"] == 3
        assert second["stats"]["indexed"] == 0
        assert second["stats"]["deduped"] == 0

        with tenant_session(alice_id) as db:
            doc_after = db.get(Document, uuid.UUID(doc_id))
            assert doc_after.removed_at is not None
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], [directory["id"]] if directory else [])


def test_delete_directory_cascade_refcount_and_hard_delete(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "removal-directory-cascade")
    contracts_dir = None
    duplicates_dir = None
    try:
        contracts_dir = _register_directory(alice, ds["id"], "alice/contracts/")
        assert _sync_and_wait(alice, contracts_dir["id"])["state"] == "succeeded"

        duplicates_dir = _register_directory(alice, ds["id"], "alice/duplicates/")
        assert _sync_and_wait(alice, duplicates_dir["id"])["state"] == "succeeded"

        alice_id = _user_id(db_conn, "alice@nimbus.dev")
        with tenant_session(alice_id) as db:
            content_hash = _find_document(db, contracts_dir["id"], "msa.md").content_hash

        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM sync_jobs WHERE directory_id = %s", (uuid.UUID(duplicates_dir["id"]),))
        db_conn.commit()

        resp = alice.delete(f"/directories/{duplicates_dir['id']}")
        assert resp.status_code == 204

        with tenant_session(alice_id) as db:
            assert _content_and_chunks_exist(db, content_hash)
            assert db.get(Directory, uuid.UUID(duplicates_dir["id"])) is None

        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM sync_jobs WHERE directory_id = %s", (uuid.UUID(contracts_dir["id"]),))
        db_conn.commit()

        resp = alice.delete(f"/directories/{contracts_dir['id']}")
        assert resp.status_code == 204

        with tenant_session(alice_id) as db:
            assert not _content_and_chunks_exist(db, content_hash)
            assert db.get(Directory, uuid.UUID(contracts_dir["id"])) is None
            remaining = db.execute(
                select(func.count()).select_from(Document).where(Document.datasource_id == uuid.UUID(ds["id"]))
            ).scalar_one()
            assert remaining == 0

        contracts_dir = None
        duplicates_dir = None
    finally:
        dir_ids = [d["id"] for d in (contracts_dir, duplicates_dir) if d is not None]
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], dir_ids)


def test_directory_deleted_mid_sync_worker_skips_remaining_files(db_conn, monkeypatch):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "removal-race-guard")
    directory = None
    job_id = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")
        alice_id = _user_id(db_conn, "alice@nimbus.dev")

        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_jobs (user_id, directory_id, state, started_at)
                VALUES (%s, %s, 'running', now())
                RETURNING id
                """,
                (alice_id, uuid.UUID(directory["id"])),
            )
            job_id = cur.fetchone()[0]
        db_conn.commit()

        real_ingest_object = sync_runner.ingest_object
        call_count = {"n": 0}

        def fake_ingest_object(db, connector, directory_row, datasource, obj, embedder):
            outcome = real_ingest_object(db, connector, directory_row, datasource, obj, embedder)
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Commit this file's work first: the concurrent DELETE below
                # opens its own connection and needs the FK's FOR KEY SHARE
                # lock released, or it blocks on this still-open transaction.
                db.commit()
                resp = alice.delete(f"/directories/{directory['id']}")
                assert resp.status_code == 204
            return outcome

        monkeypatch.setattr(sync_runner, "ingest_object", fake_ingest_object)

        sync_runner.run_sync(job_id, alice_id, uuid.UUID(directory["id"]))

        with db_conn.cursor() as cur:
            cur.execute("SELECT state, stats FROM sync_jobs WHERE id = %s", (job_id,))
            state, stats = cur.fetchone()
        assert state == "succeeded"
        assert stats["scanned"] == 3
        assert stats["indexed"] + stats["deduped"] + stats["unchanged"] == 1

        directory = None
    finally:
        if job_id is not None:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM sync_jobs WHERE id = %s", (job_id,))
            db_conn.commit()
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], [directory["id"]] if directory else [])
