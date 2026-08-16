"""Numbered-source prompt assembly. NO_SOURCES_MARKER / SOURCES_HEADER are
shared with app.rag.llm.EchoLLM, which parses this exact shape back out to
compose a grounded answer without a network call, keep the two in sync.
"""
from __future__ import annotations

from app.rag.retrieve import Source

SYSTEM_PROMPT = (
    "You answer questions using only the numbered sources below. Cite "
    "sources inline as [1], [2], etc., matching the source numbers. If the "
    "sources don't contain the answer, say you don't have information "
    "about that in the user's documents — never use outside knowledge."
)

NO_SOURCES_MARKER = "No relevant sources were found."
SOURCES_HEADER = "Sources:\n"
QUESTION_HEADER = "\n\nQuestion: "


def build_messages(question: str, sources: list[Source]) -> list[dict]:
    if not sources:
        user_content = f"{NO_SOURCES_MARKER}{QUESTION_HEADER}{question}"
    else:
        context = "\n\n".join(
            f"[{s.number}] {', '.join(s.filenames) or 'unknown file'}:\n{s.text}" for s in sources
        )
        user_content = f"{SOURCES_HEADER}{context}{QUESTION_HEADER}{question}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
