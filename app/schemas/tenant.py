from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(slots=True)
class TenantDto:
    code: str | None = None
    name: str | None = None
    description: str | None = None
    logo: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    status: str | None = None


class TenantCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=32, description="租户编码")
    name: str = Field(..., min_length=1, max_length=50, description="租户名称")
    description: str | None = Field(default=None, max_length=1000, description="租户描述")
    logo: str | None = Field(default=None, max_length=512, description="Logo 地址")
    contact_name: str | None = Field(default=None, max_length=30, description="联系人")
    contact_email: str | None = Field(default=None, max_length=128, description="联系邮箱")


class TenantModifyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50, description="租户名称")
    description: str | None = Field(default=None, max_length=1000, description="租户描述")
    logo: str | None = Field(default=None, max_length=512, description="Logo 地址")
    contact_name: str | None = Field(default=None, max_length=30, description="联系人")
    contact_email: str | None = Field(default=None, max_length=128, description="联系邮箱")
    status: str | None = Field(default=None, description="租户状态")


__all__ = ("TenantDto", "TenantCreateRequest", "TenantModifyRequest")
