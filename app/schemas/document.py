from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass(slots=True)
class DocumentCreateDto:
    knowledge_base_id: int | None = None
    source_type: str | None = None
    source_name: str | None = None
    source_uri: str | None = None
    content_type: str | None = None
    object_path: str | None = None
    file_size: int | None = None
    content_hash: str | None = None
    parser: str | None = None
    created_by: str | None = None
    status: str | None = None


@dataclass(slots=True)
class DocumentModifyDto:
    source_name: str | None = None
    source_uri: str | None = None
    content_type: str | None = None
    object_path: str | None = None
    file_size: int | None = None
    content_hash: str | None = None
    parser: str | None = None
    status: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class DocumentIndexDto:
    document_id: int | None = None
    task_type: str | None = None
    status: str | None = None
    max_attempts: int | None = None


@dataclass(slots=True)
class DocumentChunkDto:
    knowledge_base_id: int | None = None
    document_id: int | None = None
    parent_id: int | None = None
    chunk_index: int | None = None
    content: str | None = None
    content_hash: str | None = None
    source_name: str | None = None
    page: int | None = None
    section: str | None = None
    start_index: int | None = None
    token_count: int | None = None
    metadata: dict[str, Any] | None = None
    embedding_model: str | None = None
    embedding: list[float] | None = None


class DocumentCreateRequest(BaseModel):
    knowledge_base_id: int = Field(..., description="知识库 ID")
    source_type: str = Field(..., description="来源类型")
    source_name: str = Field(..., description="来源名称")
    source_uri: str | None = Field(default=None, description="原始来源 URI")
    content_type: str = Field(..., description="内容类型")
    object_path: str = Field(..., description="对象存储路径或本地路径")
    file_size: int | None = Field(default=None, description="文件大小")
    content_hash: str = Field(..., description="内容 Hash")
    parser: str | None = Field(default=None, description="解析器")
    created_by: str = Field(..., description="创建人")
    status: str | None = Field(default=None, description="文档状态")


class DocumentModifyRequest(BaseModel):
    source_name: str | None = Field(default=None, description="来源名称")
    source_uri: str | None = Field(default=None, description="原始来源 URI")
    content_type: str | None = Field(default=None, description="内容类型")
    object_path: str | None = Field(default=None, description="对象存储路径或本地路径")
    file_size: int | None = Field(default=None, description="文件大小")
    content_hash: str | None = Field(default=None, description="内容 Hash")
    parser: str | None = Field(default=None, description="解析器")
    status: str | None = Field(default=None, description="文档状态")
    error_message: str | None = Field(default=None, description="错误信息")


__all__ = (
    "DocumentCreateDto",
    "DocumentModifyDto",
    "DocumentIndexDto",
    "DocumentChunkDto",
    "DocumentCreateRequest",
    "DocumentModifyRequest",
)
