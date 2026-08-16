import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.domain.models import Chunk, Content, Datasource, Directory, Document
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
    """documents now really get written (unlike the pre-ingest worker), and
    they FK-reference directories with no cascade, so they must be deleted
    first. contents/chunks are content-addressed and deliberately left in
    place, shared, idempotent state across tests, not per-test scratch."""
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


def test_fresh_sync_ingests_and_extracts_pdf(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "dedup-fresh-ingest")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")

        job = _sync_and_wait(alice, directory["id"])
        assert job["state"] == "succeeded"
        stats = job["stats"]
        assert stats["scanned"] == 3
        assert stats["unchanged"] == 0
        # Fresh directory to layer 1 always misses (no prior etag/size to
        # compare against), regardless of whether other tests already
        # populated `contents` for these same fixture bytes.
        assert stats["downloaded"] == 3
        assert stats["indexed"] + stats["deduped"] == 3

        alice_id = _user_id(db_conn, "alice@nimbus.dev")
        with tenant_session(alice_id) as db:
            pdf_doc = db.execute(
                select(Document).where(
                    Document.directory_id == uuid.UUID(directory["id"]),
                    Document.filename == "policy.pdf",
                )
            ).scalar_one()
            content = db.get(Content, pdf_doc.content_hash)
            assert content.mime == "application/pdf"
            assert content.text_len > 0
            assert content.chunk_count >= 1
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], [directory["id"]] if directory else [])


def test_second_sync_of_unchanged_directory_skips_everything(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "dedup-unchanged-resync")
    directory = None
    try:
        directory = _register_directory(alice, ds["id"], "alice/contracts/")

        first = _sync_and_wait(alice, directory["id"])
        assert first["state"] == "succeeded"

        second = _sync_and_wait(alice, directory["id"])
        assert second["state"] == "succeeded"
        assert second["stats"] == {"scanned": 3, "unchanged": 3, "downloaded": 0, "indexed": 0, "deduped": 0}
    finally:
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], [directory["id"]] if directory else [])


def test_duplicate_file_across_directories_dedupes_content(db_conn):
    alice = _client_as("alice@nimbus.dev")
    ds = _create_datasource(alice, "dedup-cross-directory")
    contracts_dir = None
    duplicates_dir = None
    try:
        contracts_dir = _register_directory(alice, ds["id"], "alice/contracts/")
        contracts_job = _sync_and_wait(alice, contracts_dir["id"])
        assert contracts_job["state"] == "succeeded"

        duplicates_dir = _register_directory(alice, ds["id"], "alice/duplicates/")
        duplicates_job = _sync_and_wait(alice, duplicates_dir["id"])
        assert duplicates_job["state"] == "succeeded"
        # msa_copy.md is byte-identical to msa.md, already synced above in
        # this same test to layer 1 misses (new path), layer 2 hits.
        assert duplicates_job["stats"] == {"scanned": 1, "unchanged": 0, "downloaded": 1, "indexed": 0, "deduped": 1}

        alice_id = _user_id(db_conn, "alice@nimbus.dev")
        with tenant_session(alice_id) as db:
            msa = db.execute(
                select(Document).where(
                    Document.directory_id == uuid.UUID(contracts_dir["id"]),
                    Document.filename == "msa.md",
                )
            ).scalar_one()
            msa_copy = db.execute(
                select(Document).where(
                    Document.directory_id == uuid.UUID(duplicates_dir["id"]),
                    Document.filename == "msa_copy.md",
                )
            ).scalar_one()
            assert msa.content_hash == msa_copy.content_hash

            chunk_rows = db.execute(
                select(func.count()).select_from(Chunk).where(Chunk.content_hash == msa.content_hash)
            ).scalar_one()
            content = db.get(Content, msa.content_hash)
            assert chunk_rows == content.chunk_count
    finally:
        dir_ids = [d["id"] for d in (contracts_dir, duplicates_dir) if d is not None]
        _cleanup(db_conn, "alice@nimbus.dev", ds["id"], dir_ids)
