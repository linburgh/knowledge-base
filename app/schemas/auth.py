from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account: str = Field(..., min_length=1, max_length=255, description="用户名或邮箱")
    password: str = Field(..., min_length=1, max_length=256, description="登录密码")


__all__ = ("LoginRequest",)
