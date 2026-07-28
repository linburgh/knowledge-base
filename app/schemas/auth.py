from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account: str = Field(..., min_length=1, max_length=128, description="用户名或邮箱")
    password: str = Field(..., min_length=1, max_length=64, description="登录密码")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1, description="刷新 Token")


class TenantSelectionRequest(BaseModel):
    tenant_id: int = Field(..., gt=0, description="当前租户 ID")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


class AuthContextResponse(BaseModel):
    user: dict
    platform_roles: list[dict]
    current_tenant: dict | None = None
    tenants: list[dict] = Field(default_factory=list)
    tenant_role: str | None = None
    effective_role: str | None = None
    organizations: list[dict]


class PermissionActionResponse(BaseModel):
    id: int
    code: str
    name: str
    action_type: str


class PermissionMenuResponse(BaseModel):
    id: int
    code: str
    name: str
    route_path: str | None = None
    actions: list[PermissionActionResponse] = Field(default_factory=list)


class PermissionResponse(BaseModel):
    menus: list[PermissionMenuResponse] = Field(default_factory=list)
    action_codes: list[str] = Field(default_factory=list)


class PermissionCheckRequest(BaseModel):
    action_codes: list[str] = Field(..., min_length=1, max_length=100)


class PermissionCheckItem(BaseModel):
    action_code: str
    allowed: bool


class PermissionCheckResponse(BaseModel):
    items: list[PermissionCheckItem] = Field(default_factory=list)


__all__ = (
    "AuthContextResponse",
    "LoginRequest",
    "RefreshRequest",
    "TenantSelectionRequest",
    "TokenResponse",
    "PermissionActionResponse",
    "PermissionCheckItem",
    "PermissionCheckRequest",
    "PermissionCheckResponse",
    "PermissionMenuResponse",
    "PermissionResponse",
)
