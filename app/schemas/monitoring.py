from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import AgentSkillRef


class MonitorEventRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=96)
    source_type: str = Field(min_length=1, max_length=32)
    source_code: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)
    occurred_at: datetime
    tenant_id: int | None = None
    kb_id: int | None = None
    task_id: int | None = None
    run_id: int | None = None
    trace_id: str | None = None
    request_id: str | None = None
    stage: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_category: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    data_status: str = "ready"


class MonitorSnapshotRequest(BaseModel):
    resource_type: str
    resource_code: str
    status: str
    checked_at: datetime
    tenant_id: int | None = None
    status_value: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    error_category: str | None = None


class MetricRuleRequest(BaseModel):
    metric_code: str
    scope_type: str = "platform"
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    recovery_threshold: float | None = None
    minimum_sample_count: int = Field(default=0, ge=0)
    consecutive_periods: int = Field(default=1, ge=1)
    window_seconds: int = Field(default=300, ge=60)
    trigger_type: str = "threshold"
    recovery_periods: int = Field(default=1, ge=1)
    enabled: bool = True


class NotificationChannelRequest(BaseModel):
    channel_code: str
    channel_name: str
    channel_type: str
    endpoint_ref: str | None = None
    receiver_scope: dict[str, Any] = Field(default_factory=dict)
    status: str = "enabled"


class NotificationPolicyRequest(BaseModel):
    policy_name: str
    severity: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    event_types: list[str] = Field(default_factory=list)
    dedup_seconds: int = Field(default=300, ge=0)
    quiet_period: dict[str, Any] = Field(default_factory=dict)
    status: str = "enabled"
    channel_ids: list[int] = Field(default_factory=list)


class AlertActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class AnalysisConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    scope_key: str | None = Field(default=None, max_length=255)
    context: dict[str, Any] = Field(default_factory=dict)


class AnalysisConversationModifyRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class AnalysisMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    context: dict[str, Any] = Field(default_factory=dict)


class AnalysisTimeRange(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    timezone: str = "Asia/Shanghai"
    label: str
    source: Literal["question", "conversation"] | None = None


class AnalysisScope(BaseModel):
    type: str
    name: str


class AnalysisToolCall(BaseModel):
    name: str
    status: Literal["completed", "failed"]
    started_at: datetime | None = None
    result_count: int | None = None
    duration_ms: float | None = None
    error: str | None = None


class AnalysisPlanning(BaseModel):
    mode: Literal["llm", "fallback", "failed"]
    goal: str
    time_expression: str | None = None
    entities: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    confidence: float | None = None
    error: str | None = None
    requested_view: str | None = None
    referenced_fact_ids: list[str] = Field(default_factory=list)


class AnalysisAnswering(BaseModel):
    mode: Literal["llm", "fallback", "deterministic"]
    error: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    fact_refs: list[str] = Field(default_factory=list)
    layout_reason: str | None = None


class AnalysisMessageResponse(BaseModel):
    conversation_id: int
    user_message_id: int
    message_id: int
    intent: str
    answer: str
    conclusion: Literal["normal", "warning", "abnormal", "unknown"]
    data_status: str
    time_range: AnalysisTimeRange
    scope: AnalysisScope
    status: Literal["completed", "failed"]
    agent: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tool_calls: list[AnalysisToolCall] = Field(default_factory=list)
    planning: AnalysisPlanning
    answering: AnalysisAnswering


class MonitoringTask(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    operation: Literal["analysis", "overview"] = "analysis"


class MonitoringToolInput(BaseModel):
    window_start: datetime
    window_end: datetime
    scope_key: Literal["platform", "tenant"]


class MonitoringToolOutput(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    data_status: Literal["ready", "empty"]
    fact_type: str | None = None
    presentation: dict[str, Any] = Field(default_factory=dict)


class MonitoringToolDefinition(BaseModel):
    name: str
    read_only: bool = True
    requires_tenant_scope: bool = True
    fact_type: str | None = None
    presentation: dict[str, Any] = Field(default_factory=dict)


class MonitoringContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    tenant_id: int | None = None
    user_id: str = Field(min_length=1, max_length=128)
    role: Literal["platform_super_admin", "tenant_admin"]
    scope_key: Literal["platform", "tenant"] = "platform"
    scope_name: str | None = None
    time_range: str = "1h"
    organization_ids: list[int] = Field(default_factory=list)


class MonitoringResult(BaseModel):
    intent: str
    answer: str
    conclusion: Literal["normal", "warning", "abnormal", "unknown"]
    data_status: str
    time_range: AnalysisTimeRange
    scope: AnalysisScope
    status: Literal["completed", "failed", "stopped"]
    agent: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tool_calls: list[AnalysisToolCall] = Field(default_factory=list)
    planning: AnalysisPlanning
    answering: AnalysisAnswering
    termination_reason: str = "completed"
    model_call_count: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    skill_refs: list[AgentSkillRef] = Field(default_factory=list)
    fact_set: dict[str, Any] = Field(default_factory=dict)


class AnalysisSemanticOverview(BaseModel):
    status: str
    status_name: str
    title: str
    detail: str


class AnalysisCheck(BaseModel):
    dimension: str
    dimension_name: str
    status: str
    status_name: str
    result: str
    evidence_count: int = Field(ge=0)


class MonitoringOverviewResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    incident_id: str | None = None
    analysis_status: str
    attention_status: str
    confidence: int | None = None
    report_no: str
    generated_at: datetime
    conclusion: str
    conclusion_detail: str
    presentation_state: Literal["normal", "warning", "alert", "unknown"]
    presentation_state_name: str
    impact_overview: AnalysisSemanticOverview
    action_overview: AnalysisSemanticOverview
    checks: list[AnalysisCheck] = Field(default_factory=list)
    judgment_boundary: str
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    impacts: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    agent: str
