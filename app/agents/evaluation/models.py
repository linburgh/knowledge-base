"""自主评测 Harness 内部配置、问题、结果与指标模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

QuestionSource = Literal["imported", "generated"]
RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
Conclusion = Literal["passed", "failed", "indeterminate"]
CaseStatus = Literal["completed", "error", "timeout", "fallback"]


class Gate(BaseModel):
    """单项指标的比较运算符和通过阈值。"""
    operator: Literal[">=", "<=", ">", "<", "=="]
    value: float


class EvaluationQuestion(BaseModel):
    """一条可执行且可追溯的评测问题。"""
    question: str = Field(min_length=1, max_length=8000)
    case_id: str | None = Field(default=None, max_length=128)
    source: QuestionSource = "imported"
    question_basis: str | None = None
    expected_answer: str | None = None
    expected_sources: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def non_blank(cls, value: str) -> str:
        """去除问题首尾空白并拒绝纯空白输入。"""
        if not value.strip():
            raise ValueError("question cannot be blank")
        return value.strip()


class EvaluationConfig(BaseModel):
    """单次自主评测的范围、预算、问题来源与门禁配置。"""
    kb_id: int = Field(gt=0)
    questions_source: QuestionSource = "imported"
    questions_count: int = Field(default=20, ge=1, le=1000)
    questions_file: str | None = None
    questions_instruction: str | None = None
    business_scope_source: Literal[
        "description", "knowledge_base", "description_and_knowledge_base"
    ] = "description"
    business_description: str | None = None
    user_id: int | None = Field(default=None, gt=0)
    concurrency: int = Field(default=3, ge=1, le=32)
    request_timeout_seconds: float = Field(default=120, gt=0, le=3600)
    run_timeout_seconds: float = Field(default=3600, gt=0, le=86400)
    retry_count: int = Field(default=0, ge=0, le=5)
    max_review_rounds: int = Field(default=1, ge=0, le=3)
    max_model_calls: int = Field(default=5, ge=2, le=10)
    keep_conversation: bool = False
    gates: dict[str, Gate] = Field(default_factory=dict)


class CaseResult(BaseModel):
    """单题问答执行结果及其检索、引用和终止元数据。"""
    case_no: int = Field(gt=0)
    question: str
    question_source: QuestionSource
    question_basis: str | None = None
    answer: str | None = None
    status: CaseStatus
    termination_reason: str | None = None
    citation_count: int = 0
    hit_count: int = 0
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationAgentOutput(BaseModel):
    """Deep Agent 对评测过程给出的结构化分析结论。"""
    goal: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=2000)
    findings: list[str] = Field(default_factory=list, max_length=50)
    recommendations: list[str] = Field(default_factory=list, max_length=50)
    reviewed_case_numbers: list[int] = Field(default_factory=list, max_length=1000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    termination_reason: Literal["completed", "evidence_insufficient"] = "completed"


class MetricValue(BaseModel):
    """单项评测指标的数值、样本量和可用状态。"""
    value: float | None = None
    sample_count: int = 0
    available: bool = True
    reason: str | None = None


class EvaluationMetrics(BaseModel):
    """完整指标集、失败门禁及确定性总体结论。"""
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    failed_gates: list[str] = Field(default_factory=list)
    conclusion: Conclusion = "indeterminate"
