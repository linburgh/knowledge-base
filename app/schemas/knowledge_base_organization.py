from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeBaseOrganizationRequest(BaseModel):
    organization_id: int = Field(..., gt=0)


class KnowledgeBaseOrganizationBatchRequest(BaseModel):
    organization_ids: list[int] = Field(..., min_length=1)


__all__ = (
    "KnowledgeBaseOrganizationBatchRequest",
    "KnowledgeBaseOrganizationRequest",
)
