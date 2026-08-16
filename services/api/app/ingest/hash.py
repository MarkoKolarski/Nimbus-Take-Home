from __future__ import annotations

import hashlib

_CHUNK_BYTES = 1 << 20


def sha256_bytes(data: bytes) -> str:
    """SHA-256 of raw bytes, updated in 1MB blocks rather than one shot —
    identity of "same file" (bytes, never path/name/mtime)."""
    digest = hashlib.sha256()
    for offset in range(0, len(data), _CHUNK_BYTES):
        digest.update(data[offset : offset + _CHUNK_BYTES])
    return digest.hexdigest()
