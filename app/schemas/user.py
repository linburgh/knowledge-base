from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(slots=True)
class UserDto:
    username: str | None = None
    email: str | None = None
    phone: str | None = None
    display_name: str | None = None
    avatar: str | None = None
    external_subject: str | None = None
    password: str | None = None
    status: str | None = None


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32, description="登录名")
    email: str | None = Field(default=None, max_length=128, description="邮箱")
    phone: str | None = Field(default=None, max_length=11, description="手机号")
    display_name: str | None = Field(default=None, max_length=30, description="显示名称")
    avatar: str | None = Field(default=None, max_length=512, description="头像地址")
    external_subject: str | None = Field(default=None, max_length=128, description="外部身份标识")
    password: str | None = Field(default=None, min_length=8, max_length=64, description="初始密码")


class UserModifyRequest(BaseModel):
    email: str | None = Field(default=None, max_length=128, description="邮箱")
    phone: str | None = Field(default=None, max_length=11, description="手机号")
    display_name: str | None = Field(default=None, max_length=30, description="显示名称")
    avatar: str | None = Field(default=None, max_length=512, description="头像地址")
    status: str | None = Field(default=None, description="用户状态")
    password: str | None = Field(default=None, min_length=8, max_length=64, description="重置密码")


__all__ = ("UserDto", "UserCreateRequest", "UserModifyRequest")
