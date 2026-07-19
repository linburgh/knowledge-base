from __future__ import annotations

from pydantic import BaseModel, Field

TENANT_ROLES = {"tenant_owner", "tenant_admin", "tenant_member", "tenant_guest"}
TENANT_MEMBER_STATUSES = {"invited", "active", "disabled", "left"}


class TenantMemberRequest(BaseModel):
    user_id: int = Field(..., gt=0)
    role_code: str = "tenant_member"
    is_primary: bool = False
    status: str = "active"


class TenantMemberModifyRequest(BaseModel):
    role_code: str | None = None
    is_primary: bool | None = None
    status: str | None = None


__all__ = (
    "TENANT_MEMBER_STATUSES",
    "TENANT_ROLES",
    "TenantMemberModifyRequest",
    "TenantMemberRequest",
)
