"""Tenant-schema ORM models — declared WITHOUT schema=, resolved through
search_path (see app.tenancy.registry). One model set serves every tenant.

Column shape must stay in lockstep with app.tenancy.provision.provision_tenant();
there is no autogenerate path connecting them (migrations/env.py has
target_metadata = None, and tenant schemas are DDL, not Alembic-managed).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, ForeignKey, Integer, Text, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Datasource(Base):
    __tablename__ = "datasources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    config_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Directory(Base):
    __tablename__ = "directories"
    __table_args__ = (UniqueConstraint("datasource_id", "prefix"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    datasource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("datasources.id"), nullable=False)
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("directory_id", "source_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    directory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("directories.id"), nullable=False)
    datasource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("datasources.id"), nullable=False)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text)
    remote_etag: Mapped[str | None] = mapped_column(Text)
    remote_size: Mapped[int | None] = mapped_column(BigInteger)
    remote_modified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    state: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Content(Base):
    __tablename__ = "contents"

    content_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime: Mapped[str | None] = mapped_column(Text)
    text_len: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    indexed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("content_hash", "ord"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    content_hash: Mapped[str] = mapped_column(Text, ForeignKey("contents.content_hash"), nullable=False)
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    text_: Mapped[str] = mapped_column("text", Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
