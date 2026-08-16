"""LLMClient Protocol so tests and no-key demos never touch the network.
EchoLLM is the default whenever OPENROUTER_API_KEY is unset, the whole
sync -> retrieve -> cite path still demos, the answer is just mechanical
instead of generated. It is also the default in tests via a dependency
override, so pytest never spends OpenRouter credit regardless of what key
happens to be in the running container's .env.
"""
from __future__ import annotations

from typing import Protocol

import httpx

from app.core.config import settings
from app.rag.prompt import NO_SOURCES_MARKER, QUESTION_HEADER, SOURCES_HEADER

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_MODEL = "openai/gpt-4o-mini"
_ECHO_SNIPPET_CHARS = 300


class LLMClient(Protocol):
    def generate(self, messages: list[dict]) -> str: ...


class OpenRouterLLM:
    def __init__(self, api_key: str, model: str = _MODEL) -> None:
        self._api_key = api_key
        self._model = model

    def generate(self, messages: list[dict]) -> str:
        resp = httpx.post(
            _OPENROUTER_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "messages": messages},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class EchoLLM:
    def generate(self, messages: list[dict]) -> str:
        user_content = messages[-1]["content"]
        if user_content.startswith(NO_SOURCES_MARKER):
            return "I don't have anything about that in your documents."

        sources_block = user_content[len(SOURCES_HEADER):].split(QUESTION_HEADER)[0]
        snippets = [block.strip()[:_ECHO_SNIPPET_CHARS] for block in sources_block.split("\n\n")]
        return "Based on your documents:\n\n" + "\n\n".join(snippets)


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenRouterLLM(settings.openrouter_api_key) if settings.openrouter_api_key else EchoLLM()
    return _llm_client
