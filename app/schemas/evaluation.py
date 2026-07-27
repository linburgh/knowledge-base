from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvaluationTaskRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    kb_id: int = Field(gt=0)
    questions_source: str = "imported"
    questions_file: str | None = Field(default=None, max_length=100)
    questions_content: str | None = Field(default=None, max_length=10 * 1024 * 1024)
    questions_instruction: str | None = Field(default=None, max_length=1000)
    questions_count: int = Field(default=20, ge=1, le=1000)
    business_scope_source: str = "description"
    business_description: str | None = Field(default=None, max_length=2000)
    execution: dict[str, Any] = Field(default_factory=dict)
    gates: dict[str, Any] = Field(default_factory=dict)


class EvaluationRunRequest(BaseModel):
    pass


class OptimizationRequest(BaseModel):
    candidate_config: dict[str, Any] = Field(default_factory=dict)
