from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeBaseUserRequest(BaseModel):
    user_id: int = Field(..., gt=0)


class KnowledgeBaseUserBatchRequest(BaseModel):
    user_ids: list[int] = Field(..., min_length=1)


__all__ = ("KnowledgeBaseUserBatchRequest", "KnowledgeBaseUserRequest")
