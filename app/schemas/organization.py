from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(slots=True)
class OrganizationDto:
    tenant_id: int | None = None
    parent_id: int | None = None
    code: str | None = None
    name: str | None = None
    leader_user_id: int | None = None
    status: str | None = None


@dataclass(slots=True)
class OrganizationMemberDto:
    organization_id: int | None = None
    user_id: int | None = None
    role_code: str | None = None
    is_primary: bool | None = None
    status: str | None = None


class OrganizationCreateRequest(BaseModel):
    tenant_id: int = Field(..., gt=0, description="租户 ID")
    parent_id: int | None = Field(default=None, gt=0, description="父组织 ID")
    code: str = Field(..., min_length=1, max_length=32, description="组织编码")
    name: str = Field(..., min_length=1, max_length=50, description="组织名称")
    leader_user_id: int | None = Field(default=None, gt=0, description="负责人用户 ID")


class OrganizationModifyRequest(BaseModel):
    parent_id: int | None = Field(default=None, gt=0, description="父组织 ID")
    name: str | None = Field(default=None, min_length=1, max_length=50, description="组织名称")
    leader_user_id: int | None = Field(default=None, gt=0, description="负责人用户 ID")
    status: str | None = Field(default=None, description="组织状态")


class OrganizationMemberRequest(BaseModel):
    user_id: int = Field(..., gt=0, description="用户 ID")
    role_code: str = Field(default="org_member", description="组织角色")
    is_primary: bool = Field(default=False, description="是否主组织")
    status: str = Field(default="active", description="成员状态")


class OrganizationMemberModifyRequest(BaseModel):
    role_code: str | None = Field(default=None, description="组织角色")
    is_primary: bool | None = Field(default=None, description="是否主组织")
    status: str | None = Field(default=None, description="成员状态")


__all__ = (
    "OrganizationDto",
    "OrganizationMemberDto",
    "OrganizationCreateRequest",
    "OrganizationModifyRequest",
    "OrganizationMemberRequest",
    "OrganizationMemberModifyRequest",
)
