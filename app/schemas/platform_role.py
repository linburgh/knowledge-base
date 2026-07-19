from __future__ import annotations

from pydantic import BaseModel, Field


class PlatformRoleResponse(BaseModel):
    id: int
    code: str
    name: str
    description: str = ""
    status: str


class PlatformRoleAssignmentRequest(BaseModel):
    role_codes: list[str] = Field(default_factory=list, description="平台角色编码列表")


__all__ = ("PlatformRoleAssignmentRequest", "PlatformRoleResponse")
