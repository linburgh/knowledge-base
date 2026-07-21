from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PlatformMetricResponse(BaseModel):
    user_total: int
    active_user_total: int
    tenant_total: int
    active_tenant_total: int
    organization_total: int
    knowledge_base_total: int


class PlatformTrendPointResponse(BaseModel):
    date: datetime
    new_users: int
    active_users: int
    new_knowledge_bases: int


class KnowledgeBaseTrendPointResponse(BaseModel):
    date: datetime
    new_knowledge_bases: int


class TenantResourceResponse(BaseModel):
    tenant_id: int
    tenant_code: str
    tenant_name: str
    user_total: int
    organization_total: int
    knowledge_base_total: int


class DocumentStatusResponse(BaseModel):
    status: str
    total: int


class PlatformActivityResponse(BaseModel):
    id: int
    actor_id: str
    action: str
    action_cn: str
    target_type: str
    target_id: str | None = None
    result: str
    created_at: datetime


class PlatformOverviewResponse(BaseModel):
    range: str
    start_at: datetime
    end_at: datetime
    metrics: PlatformMetricResponse
    user_trend: list[PlatformTrendPointResponse]
    tenant_resources: list[TenantResourceResponse]
    knowledge_base_trend: list[KnowledgeBaseTrendPointResponse]
    document_status: list[DocumentStatusResponse]
    recent_activities: list[PlatformActivityResponse]


__all__ = (
    "DocumentStatusResponse",
    "KnowledgeBaseTrendPointResponse",
    "PlatformActivityResponse",
    "PlatformMetricResponse",
    "PlatformOverviewResponse",
    "PlatformTrendPointResponse",
    "TenantResourceResponse",
)
