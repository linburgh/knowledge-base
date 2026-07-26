from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvaluationTaskRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kb_id: int = Field(gt=0)
    questions_source: str = "imported"
    questions_file: str | None = None
    questions_content: str | None = None
    questions_instruction: str | None = None
    questions_count: int = Field(default=20, ge=1, le=1000)
    business_scope_source: str = "description"
    business_description: str | None = None
    execution: dict[str, Any] = Field(default_factory=dict)
    gates: dict[str, Any] = Field(default_factory=dict)


class EvaluationRunRequest(BaseModel):
    pass


class OptimizationRequest(BaseModel):
    candidate_config: dict[str, Any] = Field(default_factory=dict)
