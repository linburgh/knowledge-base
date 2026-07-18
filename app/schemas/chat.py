from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    kb_id: int = Field(..., gt=0, description="知识库 ID")
    question: str = Field(..., min_length=1, max_length=8000, description="用户问题")
    conversation_id: int | None = Field(default=None, gt=0, description="已有会话 ID")
    user_id: str = Field(..., min_length=1, max_length=128, description="用户 ID")
    top_k: int | None = Field(default=None, ge=1, le=50, description="召回数量")


class CitationDto(BaseModel):
    document_id: int
    chunk_id: int
    source_name: str
    page: int | None = None
    snippet: str
    score: float | None = None
    rank: int


class RetrievalInfoDto(BaseModel):
    top_k: int
    hit_count: int
    mode: str = "vector"


class ChatResponse(BaseModel):
    conversation_id: int
    message_id: int
    answer: str
    citations: list[CitationDto]
    retrieval: RetrievalInfoDto


__all__ = (
    "ChatRequest",
    "CitationDto",
    "RetrievalInfoDto",
    "ChatResponse",
)
