from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

EXPECTED_SCHEMAS = ["tenant_alice", "tenant_bob"]
EXPECTED_TENANT_TABLES = {
    "datasources",
    "directories",
    "documents",
    "contents",
    "chunks",
    "chats",
    "chat_messages",
}
EXPECTED_FIXTURE_KEYS = {
    "alice/contracts/msa.md",
    "alice/contracts/nda.txt",
    "alice/contracts/policy.pdf",
    "alice/duplicates/msa_copy.md",
    "bob/contracts/onboarding.md",
    "bob/contracts/handbook.txt",
}


def test_health_ok():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_tenant_schemas_provisioned(db_conn):
    with db_conn.cursor() as cur:
        for schema in EXPECTED_SCHEMAS:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                (schema,),
            )
            tables = {row[0] for row in cur.fetchall()}
            assert EXPECTED_TENANT_TABLES <= tables


def test_fixtures_uploaded_to_s3(s3_client):
    resp = s3_client.list_objects_v2(Bucket=settings.s3_bucket_name)
    keys = {obj["Key"] for obj in resp.get("Contents", [])}
    assert EXPECTED_FIXTURE_KEYS <= keys
