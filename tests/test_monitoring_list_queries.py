from __future__ import annotations

import pytest

from app.core.common.auth import CurrentUser
from app.core.services import monitoring
from app.db import api as db_api
from app.db.base import DB


@pytest.fixture
def list_context(monkeypatch):
    database = object()

    async def inject_db():
        DB.set(database)

    async def allow(*_):
        return {}

    async def scope(*_):
        return None

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring, "tenant_scope", scope)
    return CurrentUser(user_id="11")


@pytest.mark.asyncio
async def test_metric_and_task_pages_apply_query_and_pagination(list_context, monkeypatch):
    async def metrics(*_, **__):
        return [
            {"metric_code": "qa_success_rate", "scope_key": "qa", "data_status": "ready"},
            {"metric_code": "qa_latency", "scope_key": "qa", "data_status": "warning"},
            {"metric_code": "db_usage", "scope_key": "platform", "data_status": "ready"},
        ]

    async def events(*_, **__):
        return [
            {"source_code": "evaluation-1", "source_type": "evaluation", "status": "running"},
            {"source_code": "index-1", "source_type": "task", "status": "failed"},
            {"source_code": "api", "source_type": "service", "status": "healthy"},
        ]

    monkeypatch.setattr(monitoring.value_db, "list", metrics)
    monkeypatch.setattr(monitoring.event_db, "list", events)

    metric_result = await monitoring.metric_page(
        list_context, 1, 10, "qa", "qa", "ready"
    )
    task_result = await monitoring.task_page(
        list_context, 1, 10, "evaluation", "evaluation", "running"
    )

    assert metric_result["total"] == 1
    assert metric_result["items"][0]["metric_code"] == "qa_success_rate"
    assert task_result["total"] == 1
    assert task_result["items"][0]["source_code"] == "evaluation-1"


@pytest.mark.asyncio
async def test_event_alert_and_audit_pages_apply_all_query_fields(list_context, monkeypatch):
    async def events(*_, **__):
        return [
            {
                "event_type": "task_failed",
                "source_code": "index-worker",
                "status": "failed",
            },
            {"event_type": "task_failed", "source_code": "evaluation", "status": "failed"},
        ]

    async def alerts(*_, **__):
        return [
            {"severity": "critical", "status": "firing", "resource_code": "index-worker"},
            {"severity": "critical", "status": "firing", "resource_code": "database"},
        ]

    async def audits(*_, **__):
        return [
            {
                "actor_id": "11",
                "action": "monitor_alert_acknowledge",
                "result": "success",
                "target_id": "alert-7",
            },
            {
                "actor_id": "12",
                "action": "monitor_alert_acknowledge",
                "result": "success",
                "target_id": "alert-8",
            },
        ]

    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring.alert_db, "list", alerts)
    monkeypatch.setattr(monitoring.audit_log_db, "list", audits)

    event_result = await monitoring.event_page(
        list_context, 1, 10, "task_failed", "index", "failed"
    )
    alert_result = await monitoring.alert_page(
        list_context, 1, 10, "firing", "critical", "index"
    )
    audit_result = await monitoring.audit_page(
        list_context,
        1,
        10,
        "11",
        "monitor_alert_acknowledge",
        "success",
        "alert-7",
    )

    assert event_result["total"] == 1
    assert alert_result["total"] == 1
    assert audit_result["total"] == 1


@pytest.mark.asyncio
async def test_rule_channel_and_policy_pages_return_backend_totals(list_context, monkeypatch):
    async def rules(*_, **__):
        return [
            {"metric_code": "qa_error_rate", "enabled": True},
            {"metric_code": "db_usage", "enabled": True},
        ]

    async def channels(*_, **__):
        return [
            {"channel_name": "平台 Webhook"},
            {"channel_name": "站内通知"},
        ]

    async def policies(*_, **__):
        return [
            {"policy_name": "严重告警通知"},
            {"policy_name": "普通告警通知"},
        ]

    monkeypatch.setattr(monitoring.rule_db, "list", rules)
    monkeypatch.setattr(monitoring.channel_db, "list", channels)
    monkeypatch.setattr(monitoring.policy_db, "list", policies)

    rule_result = await monitoring.rule_page(list_context, 1, 10, "qa", True)
    channel_result = await monitoring.channel_page(list_context, 1, 10, "Webhook")
    policy_result = await monitoring.policy_page(list_context, 1, 10, "严重")

    assert rule_result["total"] == 1
    assert channel_result["total"] == 1
    assert policy_result["total"] == 1
