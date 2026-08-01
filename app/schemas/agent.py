from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AgentMode = Literal["single_retrieval", "tool_loop"]
AgentStatus = Literal["created", "running", "completed", "failed", "stopped"]
AgentTerminationReason = Literal[
    "completed",
    "evidence_insufficient",
    "fallback",
    "timeout",
    "budget_exceeded",
    "permission_denied",
    "output_invalid",
    "cancelled",
    "tool_failed",
]
ToolName = Literal[
    "retrieve_knowledge",
    "load_conversation_history",
    "build_citations",
]


class AgentTask(BaseModel):
    kb_id: int = Field(..., gt=0)
    question: str = Field(..., min_length=1, max_length=8000)
    conversation_id: int | None = Field(default=None, gt=0)
    user_id: str = Field(..., min_length=1, max_length=128)
    top_k: int | None = Field(default=None, ge=1, le=50)

    @field_validator("question", "user_id")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be blank")
        return value


class AgentContext(BaseModel):
    tenant_id: int | None = None
    organization_ids: list[int] = Field(default_factory=list)
    user_id: str = Field(..., min_length=1, max_length=128)
    kb_id: int = Field(..., gt=0)
    conversation_id: int | None = Field(default=None, gt=0)
    index_version_id: int | None = Field(default=None, gt=0)
    knowledge_base_prompt: str | None = None
    qa_config: dict[str, Any] = Field(default_factory=dict)
    purpose: Literal["business", "monitor_probe"] = "business"
    access_level: Literal["platform_admin", "tenant_member", "evaluation", "monitor_probe"] = (
        "platform_admin"
    )


class AgentSkillRef(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    version: str = Field(..., min_length=8, max_length=64)


class AgentToolTrace(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    status: Literal["completed", "failed", "timeout", "denied"]
    duration_ms: int = Field(default=0, ge=0)
    result_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=128)


class ToolCall(BaseModel):
    call_id: str = Field(..., min_length=1, max_length=64)
    name: ToolName
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    call_id: str = Field(..., min_length=1, max_length=64)
    name: ToolName
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    hit_count: int = 0


class RetrievalToolInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=8000)
    top_k: int | None = Field(default=None, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query cannot be blank")
        return value


class RetrievalToolOutput(BaseModel):
    kb_id: int
    query: str
    mode: str
    top_k: int
    chunks: list[dict[str, Any]]


class HistoryToolInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class HistoryToolOutput(BaseModel):
    conversation_id: int | None
    messages: list[dict[str, Any]]


class CitationToolInput(BaseModel):
    chunks: list[dict[str, Any]] = Field(default_factory=list)


class CitationCandidate(BaseModel):
    document_id: int
    chunk_id: int
    source_name: str
    page: int | None = None
    snippet: str
    score: float | None = None
    rank: int


class CitationToolOutput(BaseModel):
    citations: list[CitationCandidate]


class AgentAnswer(BaseModel):
    answer: str = Field(..., min_length=1)
    citation_chunk_ids: list[int] = Field(default_factory=list)
    termination_reason: str = Field(default="completed", min_length=1)


class AgentResult(BaseModel):
    answer: str = Field(..., min_length=1)
    citations: list[CitationCandidate] = Field(default_factory=list)
    mode: AgentMode
    status: AgentStatus
    top_k: int
    hit_count: int
    tool_call_count: int = 0
    model_call_count: int = 0
    termination_reason: str
    duration_ms: int
    tool_calls: list[AgentToolTrace] = Field(default_factory=list)
    skill_refs: list[AgentSkillRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


__all__ = (
    "AgentAnswer",
    "AgentContext",
    "AgentMode",
    "AgentResult",
    "AgentSkillRef",
    "AgentStatus",
    "AgentTask",
    "AgentTerminationReason",
    "AgentToolTrace",
    "CitationCandidate",
    "CitationToolInput",
    "CitationToolOutput",
    "HistoryToolInput",
    "HistoryToolOutput",
    "RetrievalToolInput",
    "RetrievalToolOutput",
    "ToolCall",
    "ToolName",
    "ToolResult",
)
