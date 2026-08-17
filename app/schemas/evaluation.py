from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.agent import AgentResult, AgentSkillRef, AgentToolTrace


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


class EvaluationAgentTask(BaseModel):
    config: dict[str, Any]
    questions: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class EvaluationAgentContext(BaseModel):
    run_id: int = Field(gt=0)
    task_id: int = Field(gt=0)
    user_id: str = Field(min_length=1, max_length=128)
    tenant_id: int | None = None
    organization_ids: list[int] = Field(default_factory=list)
    kb_id: int = Field(gt=0)
    index_version_id: int | None = Field(default=None, gt=0)
    knowledge_base_prompt: str | None = None
    qa_config: dict[str, Any] = Field(default_factory=dict)
    is_super_admin: bool = False
    monitoring_fields: dict[str, Any] = Field(default_factory=dict)


class KnowledgeAgentCall(BaseModel):
    case_no: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=8000)
    top_k: int | None = Field(default=None, ge=1, le=50)


class KnowledgeAgentCallResult(BaseModel):
    result: AgentResult


class EvaluationRunSummary(BaseModel):
    status: str
    termination_reason: str
    tool_calls: list[AgentToolTrace] = Field(default_factory=list)
    model_call_count: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    limitations: list[str] = Field(default_factory=list)
    skill_refs: list[AgentSkillRef] = Field(default_factory=list)
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)


class EvaluationAgentResult(BaseModel):
    case_results: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    report: dict[str, Any] = Field(default_factory=dict)
    conclusion: str
    summary: EvaluationRunSummary
