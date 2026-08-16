import re

from psycopg import Connection, sql


TENANT_SCHEMA_VERSION = 1


def schema_name_for(email: str) -> str:
    """Demo-friendly schema name derived from the email local-part.

    Simplification: fine for two known seed users, not collision-safe for
    arbitrary JIT-provisioned users (that's a later, v1.5 concern).
    """
    local_part = email.split("@")[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "_", local_part).strip("_")
    return f"tenant_{slug}"


def provision_tenant(conn: Connection, schema_name: str) -> None:
    """Create a tenant's data-plane schema and its full table set.

    Schema name is always interpolated through psycopg.sql.Identifier, never
    string-formatted, mirroring the identifier-safety rule BUILDPLAN.md §3
    states for the (later) SET LOCAL search_path code. Runs as part of the
    caller's transaction so schema creation, table DDL, and the caller's
    public.tenants insert commit or roll back together.
    """
    schema = sql.Identifier(schema_name)

    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(schema))

        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {schema}.datasources (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    config_encrypted TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            ).format(schema=schema)
        )

        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {schema}.directories (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    datasource_id UUID NOT NULL REFERENCES {schema}.datasources(id),
                    prefix TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (datasource_id, prefix)
                )
                """
            ).format(schema=schema)
        )

        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {schema}.documents (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    directory_id UUID NOT NULL REFERENCES {schema}.directories(id),
                    datasource_id UUID NOT NULL REFERENCES {schema}.datasources(id),
                    source_key TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_hash TEXT,
                    remote_etag TEXT,
                    remote_size BIGINT,
                    remote_modified_at TIMESTAMPTZ,
                    state TEXT NOT NULL,
                    error TEXT,
                    indexed_at TIMESTAMPTZ,
                    removed_at TIMESTAMPTZ,
                    UNIQUE (directory_id, source_key)
                )
                """
            ).format(schema=schema)
        )

        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {schema}.contents (
                    content_hash TEXT PRIMARY KEY,
                    byte_size BIGINT NOT NULL,
                    mime TEXT,
                    text_len INT,
                    chunk_count INT,
                    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            ).format(schema=schema)
        )

        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {schema}.chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    content_hash TEXT NOT NULL REFERENCES {schema}.contents(content_hash),
                    ord INT NOT NULL,
                    text TEXT NOT NULL,
                    token_count INT,
                    embedding vector(384),
                    UNIQUE (content_hash, ord)
                )
                """
            ).format(schema=schema)
        )

        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {schema}.chats (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    title TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            ).format(schema=schema)
        )

        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {schema}.chat_messages (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    chat_id UUID NOT NULL REFERENCES {schema}.chats(id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    citations JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            ).format(schema=schema)
        )
