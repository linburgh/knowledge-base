from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeBaseRequest(BaseModel):
    name: str = Field(..., description="知识库名称")
    owner_id: str = Field(..., description="所有者用户 ID")
    description: str | None = Field(default=None, description="知识库描述")
    visibility: str | None = Field(default=None, description="可见范围")
    embedding_model: str | None = Field(default=None, description="Embedding 模型")
    chunk_size: int | None = Field(default=None, description="默认切片大小")
    chunk_overlap: int | None = Field(default=None, description="默认切片重叠")
    retrieval_top_k: int | None = Field(default=None, description="默认召回数量")
    status: str | None = Field(default=None, description="知识库状态")


__all__ = ("KnowledgeBaseRequest",)
