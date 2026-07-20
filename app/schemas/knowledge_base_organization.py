from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeBaseOrganizationRequest(BaseModel):
    organization_id: int = Field(..., gt=0)


__all__ = ("KnowledgeBaseOrganizationRequest",)
