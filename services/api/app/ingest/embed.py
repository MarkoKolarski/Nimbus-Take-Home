"""Local embedding. Embedder Protocol so a
future backend can swap in without touching ingest/index.py.
"""
from __future__ import annotations

from typing import Protocol

EMBEDDING_DIM = 384
_MODEL_NAME = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(_MODEL_NAME)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Lazily loaded, cached per process, model init is expensive and the
    worker/api process lives far longer than any single sync job."""
    global _embedder
    if _embedder is None:
        _embedder = FastEmbedEmbedder()
    return _embedder
