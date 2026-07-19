from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account: str = Field(..., min_length=1, max_length=255, description="用户名或邮箱")
    password: str = Field(..., min_length=1, max_length=256, description="登录密码")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1, description="刷新 Token")


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
    tenant_role: str | None = None
    organizations: list[dict]


__all__ = (
    "AuthContextResponse",
    "LoginRequest",
    "RefreshRequest",
    "TokenResponse",
)
