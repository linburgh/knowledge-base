from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.core.common import auth, utils
from app.core.common.exception import BusiException
from app.core.services.monitoring import analysis as analysis_service
from app.core.services.monitoring import mgr as service
from app.schemas.monitoring import (
    AlertActionRequest,
    AnalysisConversationRequest,
    AnalysisConversationModifyRequest,
    AnalysisMessageRequest,
    AnalysisMessageResponse,
    MetricRuleRequest,
    MonitorEventRequest,
    MonitorSnapshotRequest,
    NotificationChannelRequest,
    NotificationPolicyRequest,
)

router = APIRouter()
current_user_dependency = Depends(auth.get_current_user)


async def _call(function, *args, **kwargs) -> Any:
    try:
        return await function(*args, **kwargs)
    except BusiException as exc:
        utils.raise_http_exception(exc)


@router.get("/overview")
async def get_overview(
    scope_key: str = "platform",
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.overview, current_user, time_range, scope_key)


@router.get("/collection/overview")
async def collection_overview(
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.collection_overview, current_user, time_range)


@router.get("/collection/targets/page")
async def target_page(
    page: int = 1,
    page_size: int = 20,
    target_name: str | None = None,
    target_type: str | None = None,
    data_status: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.target_page,
        current_user,
        page,
        page_size,
        target_name,
        target_type,
        data_status,
    )


@router.get("/metrics/overview")
async def metrics_overview(
    time_range: str = "1h",
    data_scope: str = "current",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.metrics_overview, current_user, time_range, data_scope)


@router.get("/metrics/page")
async def metric_page(
    page: int = 1,
    page_size: int = 20,
    metric_name: str | None = None,
    metric_domain: str | None = None,
    data_scope: str = "current",
    time_range: str = "1h",
    data_status: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.metric_page,
        current_user,
        page,
        page_size,
        metric_name,
        metric_domain,
        data_scope,
        time_range,
        data_status,
    )


@router.get("/tasks/overview")
async def tasks_overview(
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.tasks_overview, current_user, time_range)


@router.get("/tasks/page")
async def task_page(
    page: int = 1,
    page_size: int = 20,
    task_name: str | None = None,
    task_type: str | None = None,
    status: str | None = None,
    worker_code: str | None = None,
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.task_page,
        current_user,
        page,
        page_size,
        task_name,
        task_type,
        status,
        worker_code,
        time_range,
    )


@router.get("/tasks/{task_key}/detail")
async def task_detail(
    task_key: str,
    time_range: str = "24h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.task_detail, current_user, task_key, time_range)


@router.post("/events")
async def ingest_event(
    payload: MonitorEventRequest, current_user: auth.CurrentUser = current_user_dependency
):
    return await _call(service.ingest_event, payload, current_user)


@router.post("/snapshots")
async def ingest_snapshot(
    payload: MonitorSnapshotRequest, current_user: auth.CurrentUser = current_user_dependency
):
    return await _call(service.ingest_snapshot, payload, current_user)


@router.get("/events/page")
async def event_page(
    page: int = 1,
    page_size: int = 20,
    event_type: str | None = None,
    monitor_domain: str | None = None,
    resource_name: str | None = None,
    association_id: str | None = None,
    time_range: str = "1h",
    status: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.event_page,
        current_user,
        page,
        page_size,
        event_type,
        monitor_domain,
        resource_name,
        association_id,
        time_range,
        status,
    )


@router.get("/events/overview")
async def events_overview(
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.events_overview, current_user, time_range)


@router.get("/events/{event_id}/detail")
async def event_detail(
    event_id: str,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.event_detail, current_user, event_id)


@router.get("/alerts/page")
async def alert_page(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    severity: str | None = None,
    monitor_domain: str | None = None,
    resource_name: str | None = None,
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.alert_page,
        current_user,
        page,
        page_size,
        status,
        severity,
        monitor_domain,
        resource_name,
        time_range,
    )


@router.get("/alerts/overview")
async def alerts_overview(
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.alerts_overview, current_user, time_range)


@router.get("/alerts/{alert_id}/detail")
async def alert_detail(
    alert_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.alert_detail, current_user, alert_id)


@router.post("/alerts/{alert_id}/{action}")
async def alert_action(
    alert_id: int,
    action: str,
    payload: AlertActionRequest | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.alert_action,
        alert_id,
        action,
        current_user,
        payload.note if payload else None,
    )


@router.get("/metrics/{metric_code}")
async def metric_series(
    metric_code: str,
    scope_key: str = "platform",
    limit: int = 60,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.metric_series, current_user, metric_code, scope_key, limit)


@router.get("/metrics/{metric_code}/detail")
async def metric_detail(
    metric_code: str,
    time_range: str = "1h",
    data_scope: str = "current",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.metric_detail,
        current_user,
        metric_code,
        time_range,
        data_scope,
    )


@router.get("/rules")
async def list_rules(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.list_rules, current_user)


@router.get("/rules/page")
async def rule_page(
    page: int = 1,
    page_size: int = 20,
    rule_name: str | None = None,
    monitor_domain: str | None = None,
    severity: str | None = None,
    enabled: bool | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.rule_page,
        current_user,
        page,
        page_size,
        rule_name,
        monitor_domain,
        severity,
        enabled,
    )


@router.get("/rules/overview")
async def rules_overview(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.rules_overview, current_user)


@router.post("/rules")
async def create_rule(
    payload: MetricRuleRequest, current_user: auth.CurrentUser = current_user_dependency
):
    return await _call(service.create_rule, payload, current_user)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    payload: MetricRuleRequest,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.update_rule, rule_id, payload, current_user)


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(
    rule_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.toggle_rule, rule_id, current_user)


@router.get("/notifications/channels")
async def list_channels(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.list_channels, current_user)


@router.get("/notifications/channels/page")
async def channel_page(
    page: int = 1,
    page_size: int = 20,
    channel_name: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.channel_page,
        current_user,
        page,
        page_size,
        channel_name,
    )


@router.post("/notifications/channels")
async def create_channel(
    payload: NotificationChannelRequest, current_user: auth.CurrentUser = current_user_dependency
):
    return await _call(service.create_channel, payload, current_user)


@router.get("/notifications/policies")
async def list_policies(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.list_policies, current_user)


@router.get("/notifications/policies/page")
async def policy_page(
    page: int = 1,
    page_size: int = 20,
    policy_name: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.policy_page,
        current_user,
        page,
        page_size,
        policy_name,
    )


@router.get("/notifications/records/page")
async def notification_record_page(
    page: int = 1,
    page_size: int = 20,
    channel_type: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.notification_record_page,
        current_user,
        page,
        page_size,
        channel_type,
        status,
        severity,
        time_range,
    )


@router.get("/notifications/overview")
async def notifications_overview(
    time_range: str = "1h",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.notifications_overview, current_user, time_range)


@router.post("/notifications/policies")
async def create_policy(
    payload: NotificationPolicyRequest, current_user: auth.CurrentUser = current_user_dependency
):
    return await _call(service.create_policy, payload, current_user)


@router.post("/analysis/conversations")
async def create_conversation(
    payload: AnalysisConversationRequest, current_user: auth.CurrentUser = current_user_dependency
):
    return await _call(analysis_service.create_conversation, payload, current_user)


@router.get("/analysis/overview")
async def analysis_overview(
    time_range: str = "1h",
    scope_key: str = "platform",
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.analysis_overview, current_user, time_range, scope_key)


@router.get("/audits/page")
async def audit_page(
    page: int = 1,
    page_size: int = 20,
    actor_id: str | None = None,
    action: str | None = None,
    result: str | None = None,
    target_id: str | None = None,
    tenant_id: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.audit_page,
        current_user,
        page,
        page_size,
        actor_id,
        action,
        result,
        target_id,
        tenant_id,
        start_at,
        end_at,
    )


@router.get("/audits/options")
async def audit_options(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.audit_options, current_user)


@router.get("/audits/{audit_id}/detail")
async def audit_detail(
    audit_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.audit_detail, current_user, audit_id)


@router.get("/analysis/conversations")
async def list_conversations(
    keyword: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(analysis_service.list_conversations, current_user, keyword)


@router.put("/analysis/conversations/{conversation_id}")
async def modify_conversation(
    conversation_id: int,
    payload: AnalysisConversationModifyRequest,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        analysis_service.modify_conversation, conversation_id, payload, current_user
    )


@router.delete("/analysis/conversations/{conversation_id}")
async def remove_conversation(
    conversation_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(analysis_service.remove_conversation, conversation_id, current_user)


@router.get("/analysis/conversations/{conversation_id}/messages")
async def messages(conversation_id: int, current_user: auth.CurrentUser = current_user_dependency):
    return await _call(analysis_service.messages, conversation_id, current_user)


@router.post(
    "/analysis/conversations/{conversation_id}/messages",
    response_model=AnalysisMessageResponse,
)
async def send_message(
    conversation_id: int,
    payload: AnalysisMessageRequest,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(analysis_service.send_message, conversation_id, payload, current_user)
