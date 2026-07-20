from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


@dataclass(slots=True)
class ConversationDto:
    kb_id: int | None = None
    user_id: str | None = None
    title: str | None = None
    status: str | None = None


class ConversationCreateRequest(BaseModel):
    kb_id: int = Field(..., description="知识库 ID")
    user_id: str = Field(..., description="用户 ID")
    title: str | None = Field(default=None, description="会话标题")
    status: str | None = Field(default=None, description="会话状态")


class ConversationModifyRequest(BaseModel):
    title: str | None = Field(default=None, description="会话标题")
    status: str | None = Field(default=None, description="会话状态")


class GuestConversationModifyRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="会话标题")


@dataclass(slots=True)
class ConversationMessageDto:
    conversation_id: int | None = None
    kb_id: int | None = None
    user_id: str | None = None
    role: str | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None


class ConversationMessageCreateRequest(BaseModel):
    role: str = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")
    metadata: dict[str, Any] | None = Field(default=None, description="消息元数据")


class ConversationMessageModifyRequest(BaseModel):
    content: str | None = Field(default=None, description="消息内容")
    metadata: dict[str, Any] | None = Field(default=None, description="消息元数据")


@dataclass(slots=True)
class MessageCitationDto:
    message_id: int | None = None
    kb_id: int | None = None
    document_id: int | None = None
    chunk_id: int | None = None
    source_name: str | None = None
    page: int | None = None
    snippet: str | None = None
    score: Decimal | float | None = None
    rank: int | None = None


class MessageCitationCreateRequest(BaseModel):
    document_id: int = Field(..., description="文档 ID")
    chunk_id: int = Field(..., description="分块 ID")
    source_name: str = Field(..., description="来源名称")
    page: int | None = Field(default=None, description="页码")
    snippet: str = Field(..., description="引用片段")
    score: Decimal | float | None = Field(default=None, description="检索或重排序分数")
    rank: int = Field(..., description="引用排序")


class MessageCitationModifyRequest(BaseModel):
    source_name: str | None = Field(default=None, description="来源名称")
    page: int | None = Field(default=None, description="页码")
    snippet: str | None = Field(default=None, description="引用片段")
    score: Decimal | float | None = Field(default=None, description="检索或重排序分数")
    rank: int | None = Field(default=None, description="引用排序")


__all__ = (
    "ConversationDto",
    "ConversationCreateRequest",
    "ConversationModifyRequest",
    "GuestConversationModifyRequest",
    "ConversationMessageDto",
    "ConversationMessageCreateRequest",
    "ConversationMessageModifyRequest",
    "MessageCitationDto",
    "MessageCitationCreateRequest",
    "MessageCitationModifyRequest",
)
