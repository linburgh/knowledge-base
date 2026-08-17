from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(slots=True)
class KnowledgeBaseDto:
    tenant_id: int | None = None
    name: str | None = None
    description: str | None = None
    owner_id: str | None = None
    visibility: str | None = None
    embedding_model: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    retrieval_top_k: int | None = None
    system_prompt: str | None = None
    status: str | None = None


class KnowledgeBaseRequest(BaseModel):
    name: str = Field(..., description="知识库名称")
    owner_id: str = Field(..., description="所有者用户 ID")
    tenant_id: int | None = Field(default=None, gt=0, description="所属租户 ID")
    description: str | None = Field(default=None, description="知识库描述")
    visibility: str | None = Field(default=None, description="可见范围")
    embedding_model: str | None = Field(default=None, description="Embedding 模型")
    chunk_size: int | None = Field(default=None, description="默认切片大小")
    chunk_overlap: int | None = Field(default=None, description="默认切片重叠")
    retrieval_top_k: int | None = Field(default=None, description="默认召回数量")
    system_prompt: str | None = Field(default=None, description="知识库独立系统提示词")
    status: str | None = Field(default=None, description="知识库状态")


__all__ = ("KnowledgeBaseDto", "KnowledgeBaseRequest")
