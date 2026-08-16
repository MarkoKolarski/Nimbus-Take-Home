"""control plane schema: users, tenants, sync_jobs

Revision ID: 0001
Revises:
Create Date: 2026-08-16

Assumption (BUILDPLAN.md v0.1-skeleton, decision #1): all three public
control-plane tables are created here in one shot, even though sync_jobs
isn't read/written by any code until the later "Sync state + worker" block.
Pure DDL with no code dependency, so there is nothing to gain by splitting
it into a second public-schema migration later.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() is native to Postgres 16 core; pgvector needs its own extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        # Not in BUILDPLAN.md §3's shorthand column list; added because the
        # (later) Auth block seeds a real email+password login, and this
        # migration is what creates the user rows (decision #3).
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "tenants",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("schema_name", sa.Text(), nullable=False, unique=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("provisioned_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "sync_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        # No FK: directory_id points into a per-tenant schema, which public
        # cannot reference (BUILDPLAN.md §3).
        sa.Column("directory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    # Single-flight guard: at most one queued/running job per directory.
    # Enforced in the database, not the application (BUILDPLAN.md §5).
    op.create_index(
        "sync_jobs_single_flight",
        "sync_jobs",
        ["directory_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("sync_jobs_single_flight", table_name="sync_jobs")
    op.drop_table("sync_jobs")
    op.drop_table("tenants")
    op.drop_table("users")
