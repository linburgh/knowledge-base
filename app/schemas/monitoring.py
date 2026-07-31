from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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


class AnalysisMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    context: dict[str, Any] = Field(default_factory=dict)
