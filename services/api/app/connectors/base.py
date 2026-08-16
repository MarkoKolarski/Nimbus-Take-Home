"""Provider-agnostic storage access. S3Connector is the only implementation
in v1.0; a future GoogleDriveConnector (v1.4) implements the same Protocol
with no changes to sync/ingest, since they only ever depend on this shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ObjectMeta:
    key: str
    etag: str
    size: int
    last_modified: datetime


class Connector(Protocol):
    def list_prefixes(self, prefix: str) -> list[str]:
        """Immediate child prefixes under `prefix` (one level, not recursive)."""
        ...

    def list_objects(self, prefix: str) -> list[ObjectMeta]:
        """All objects under `prefix`, recursively."""
        ...

    def get_object_bytes(self, key: str) -> bytes:
        ...
