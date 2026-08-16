"""one implicit chat per tenant (get-or-create). parameterizes
this same endpoint on an explicit chat_id
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Chat, ChatMessage
from app.ingest.embed import get_embedder
from app.rag.llm import LLMClient, get_llm_client
from app.rag.prompt import build_messages
from app.rag.retrieve import Source, retrieve
from app.rag.vectorstore import PgVectorStore
from app.tenancy.registry import get_tenant_db

router = APIRouter(tags=["chat"])

_vectorstore = PgVectorStore()


class ChatMessageIn(BaseModel):
    message: str


class CitationOut(BaseModel):
    number: int
    filenames: list[str]


class ChatMessageOut(BaseModel):
    answer: str
    citations: list[CitationOut]


def _get_or_create_chat(db: Session, first_message: str) -> Chat:
    chat = db.execute(select(Chat).order_by(Chat.created_at).limit(1)).scalar_one_or_none()
    if chat is None:
        chat = Chat(title=first_message[:40])
        db.add(chat)
        db.flush()
    return chat


@router.post("/chat/messages", response_model=ChatMessageOut)
def post_chat_message(
    body: ChatMessageIn,
    db: Session = Depends(get_tenant_db),
    llm: LLMClient = Depends(get_llm_client),
) -> ChatMessageOut:
    chat = _get_or_create_chat(db, body.message)
    db.add(ChatMessage(chat_id=chat.id, role="user", content=body.message))

    sources: list[Source] = retrieve(db, get_embedder(), _vectorstore, body.message)
    answer = llm.generate(build_messages(body.message, sources))
    citations = [CitationOut(number=s.number, filenames=s.filenames) for s in sources]

    db.add(
        ChatMessage(
            chat_id=chat.id,
            role="assistant",
            content=answer,
            citations=[c.model_dump() for c in citations],
        )
    )
    chat.updated_at = datetime.now(timezone.utc)

    return ChatMessageOut(answer=answer, citations=citations)
