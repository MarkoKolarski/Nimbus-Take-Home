"""Text extraction by file extension
"""
from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


class UnsupportedFileType(Exception):
    pass


def extract_text(filename: str, raw: bytes) -> tuple[str, str]:
    """Returns (text, mime). Raises UnsupportedFileType for anything outside
    the supported extensions, no per-file catch in v1.0, so this fails the
    whole sync job"""
    suffix = Path(filename).suffix.lower()
    mime = _MIME_BY_SUFFIX.get(suffix)
    if mime is None:
        raise UnsupportedFileType(f"unsupported file extension: {suffix or '(none)'}")

    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text, mime

    return raw.decode("utf-8"), mime
