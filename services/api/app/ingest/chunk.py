from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

# Chars, not tokens. 1500 chars is
# ~375 tokens by the len // 4 estimate used elsewhere in this project, 
# safely under bge-small-en-v1.5's
# 512-token limit while keeping chunks big enough to stay coherent.
_CHUNK_SIZE = 1500
_CHUNK_OVERLAP = 200

_splitter = RecursiveCharacterTextSplitter(chunk_size=_CHUNK_SIZE, chunk_overlap=_CHUNK_OVERLAP)


def chunk_text(text: str) -> list[str]:
    return _splitter.split_text(text)
