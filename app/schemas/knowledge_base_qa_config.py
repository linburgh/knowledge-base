from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeBaseQaConfigDraftRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict, description="问答配置内容")
    base_version: int | None = Field(default=None, gt=0, description="编辑时读取的配置版本")


class KnowledgeBaseQaConfigPublishRequest(BaseModel):
    base_version: int | None = Field(default=None, gt=0, description="发布时校验的草稿版本")


class KnowledgeBaseQaConfigTestRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="测试问题")
    config: dict[str, Any] | None = Field(default=None, description="临时测试配置")


class KnowledgeBaseQaConfigRerankTestResponse(BaseModel):
    success: bool
    model: str
    elapsed_ms: int
    result_count: int
    top_score: float | None = None


class KnowledgeBaseQaConfigPromptPreviewResponse(BaseModel):
    question: str
    prompt: str
    character_count: int


__all__ = (
    "KnowledgeBaseQaConfigDraftRequest",
    "KnowledgeBaseQaConfigPublishRequest",
    "KnowledgeBaseQaConfigPromptPreviewResponse",
    "KnowledgeBaseQaConfigRerankTestResponse",
    "KnowledgeBaseQaConfigTestRequest",
)
