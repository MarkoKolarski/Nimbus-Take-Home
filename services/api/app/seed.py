from pathlib import Path

import bcrypt
import boto3
import psycopg

from app.core.config import settings
from app.tenancy.provision import TENANT_SCHEMA_VERSION, provision_tenant, schema_name_for

# BUILDPLAN.md's Auth block commits to "a real email+password screen" for
# these two seeded users; this is that fixed demo password (documented in
# README once it's written in the submission phase).
DEMO_PASSWORD = "nimbus-demo"

DEMO_USERS = [
    {"email": "alice@nimbus.dev", "display_name": "Alice"},
    {"email": "bob@nimbus.dev", "display_name": "Bob"},
]


def seed_users_and_tenants(conn: psycopg.Connection) -> None:
    """Idempotent: safe to run again on a warm volume without erroring."""
    password_hash = bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt()).decode()

    for user in DEMO_USERS:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (user["email"],))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    INSERT INTO users (email, display_name, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (user["email"], user["display_name"], password_hash),
                )
                row = cur.fetchone()
                print(f"created user {user['email']}")
            user_id = row[0]

            cur.execute("SELECT 1 FROM tenants WHERE user_id = %s", (user_id,))
            if cur.fetchone() is None:
                schema_name = schema_name_for(user["email"])
                provision_tenant(conn, schema_name)
                cur.execute(
                    """
                    INSERT INTO tenants (user_id, schema_name, schema_version)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, schema_name, TENANT_SCHEMA_VERSION),
                )
                print(f"provisioned {schema_name} for {user['email']}")
            else:
                print(f"tenant already provisioned for {user['email']}")

    conn.commit()


def seed_fixtures() -> None:
    """Idempotent: bucket creation and per-key uploads both tolerate re-runs."""
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_default_region,
    )

    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if settings.s3_bucket_name not in existing:
        s3.create_bucket(Bucket=settings.s3_bucket_name)
        print(f"created bucket {settings.s3_bucket_name}")

    fixtures_dir = Path(settings.fixtures_dir)
    if not fixtures_dir.is_dir():
        print(f"no fixtures directory at {fixtures_dir}, skipping upload")
        return

    for path in sorted(fixtures_dir.rglob("*")):
        if path.is_file():
            key = path.relative_to(fixtures_dir).as_posix()
            s3.upload_file(str(path), settings.s3_bucket_name, key)
            print(f"uploaded {key}")


def main() -> None:
    with psycopg.connect(settings.database_url, autocommit=False) as conn:
        seed_users_and_tenants(conn)
    seed_fixtures()
    print("seed complete")


if __name__ == "__main__":
    main()
