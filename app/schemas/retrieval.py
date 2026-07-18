from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RetrievalMode = Literal["vector"]


class RetrievalRequest(BaseModel):
    kb_id: int = Field(..., gt=0, description="知识库 ID")
    query: str = Field(..., min_length=1, description="检索问题或关键词")
    top_k: int | None = Field(default=None, ge=1, le=50, description="返回数量")
    mode: RetrievalMode = Field(default="vector", description="检索模式")


class RetrievalChunkDto(BaseModel):
    id: int
    kb_id: int
    document_id: int
    chunk_index: int
    content: str
    source_name: str
    page: int | None = None
    section: str | None = None
    start_index: int | None = None
    token_count: int | None = None
    metadata: dict = Field(default_factory=dict)
    score: float
    distance: float | None = None


class RetrievalResponse(BaseModel):
    kb_id: int
    query: str
    mode: RetrievalMode
    top_k: int
    chunks: list[RetrievalChunkDto]


__all__ = (
    "RetrievalMode",
    "RetrievalRequest",
    "RetrievalChunkDto",
    "RetrievalResponse",
)
