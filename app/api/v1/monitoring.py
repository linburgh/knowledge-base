from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.common import auth, utils
from app.core.common.exception import BusiException
from app.core.services import monitoring as service
from app.core.services import monitoring_analysis as analysis_service
from app.schemas.monitoring import (
    AnalysisConversationRequest,
    AnalysisMessageRequest,
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
async def metrics_overview(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.metrics_overview, current_user)


@router.get("/metrics/page")
async def metric_page(
    page: int = 1,
    page_size: int = 20,
    metric_name: str | None = None,
    scope_key: str | None = None,
    data_status: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.metric_page,
        current_user,
        page,
        page_size,
        metric_name,
        scope_key,
        data_status,
    )


@router.get("/tasks/overview")
async def tasks_overview(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.tasks_overview, current_user)


@router.get("/tasks/page")
async def task_page(
    page: int = 1,
    page_size: int = 20,
    task_name: str | None = None,
    task_type: str | None = None,
    status: str | None = None,
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
    )


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
    source_code: str | None = None,
    status: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.event_page,
        current_user,
        page,
        page_size,
        event_type,
        source_code,
        status,
    )


@router.get("/alerts/page")
async def alert_page(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    severity: str | None = None,
    resource_code: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.alert_page,
        current_user,
        page,
        page_size,
        status,
        severity,
        resource_code,
    )


@router.post("/alerts/{alert_id}/{action}")
async def alert_action(
    alert_id: int, action: str, current_user: auth.CurrentUser = current_user_dependency
):
    return await _call(service.alert_action, alert_id, action, current_user)


@router.get("/metrics/{metric_code}")
async def metric_series(
    metric_code: str,
    scope_key: str = "platform",
    limit: int = 60,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.metric_series, current_user, metric_code, scope_key, limit)


@router.get("/rules")
async def list_rules(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.list_rules, current_user)


@router.get("/rules/page")
async def rule_page(
    page: int = 1,
    page_size: int = 20,
    metric_name: str | None = None,
    enabled: bool | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(
        service.rule_page,
        current_user,
        page,
        page_size,
        metric_name,
        enabled,
    )


@router.post("/rules")
async def create_rule(
    payload: MetricRuleRequest, current_user: auth.CurrentUser = current_user_dependency
):
    return await _call(service.create_rule, payload, current_user)


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
    status: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(service.notification_record_page, current_user, page, page_size, status)


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
async def analysis_overview(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(service.analysis_overview, current_user)


@router.get("/audits/page")
async def audit_page(
    page: int = 1,
    page_size: int = 20,
    actor_id: str | None = None,
    action: str | None = None,
    result: str | None = None,
    target_id: str | None = None,
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
    )


@router.get("/analysis/conversations")
async def list_conversations(current_user: auth.CurrentUser = current_user_dependency):
    return await _call(analysis_service.list_conversations, current_user)


@router.get("/analysis/conversations/{conversation_id}/messages")
async def messages(conversation_id: int, current_user: auth.CurrentUser = current_user_dependency):
    return await _call(analysis_service.messages, conversation_id, current_user)


@router.post("/analysis/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    payload: AnalysisMessageRequest,
    current_user: auth.CurrentUser = current_user_dependency,
):
    return await _call(analysis_service.send_message, conversation_id, payload, current_user)
