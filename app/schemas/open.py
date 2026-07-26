from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.retrieval import RetrievalMode


class OpenSearchRequest(BaseModel):
    knowledge_base_id: int = Field(..., gt=0)
    query: str = Field(..., min_length=1, max_length=8000)
    mode: RetrievalMode = "vector"
    top_k: int = Field(default=5, ge=1, le=50)


class OpenChatRequest(BaseModel):
    knowledge_base_id: int = Field(..., gt=0)
    question: str = Field(..., min_length=1, max_length=8000)
    conversation_id: int | None = Field(default=None, gt=0)
    top_k: int | None = Field(default=None, ge=1, le=50)


class OpenMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)


__all__ = ("OpenSearchRequest", "OpenChatRequest", "OpenMessageRequest")
