from __future__ import annotations

from pydantic import BaseModel, Field


class OrganizationMemberBatchItem(BaseModel):
    user_id: int = Field(..., gt=0)
    role_code: str = "org_member"
    is_primary: bool = False
    status: str = "active"


class OrganizationMemberBatchRequest(BaseModel):
    members: list[OrganizationMemberBatchItem] = Field(default_factory=list)


__all__ = ("OrganizationMemberBatchItem", "OrganizationMemberBatchRequest")
