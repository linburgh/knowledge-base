from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.common import utils
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
    now = utils.utc_now()

    async def metrics(*_, **__):
        return [
            {
                "metric_code": "qa_success_rate",
                "scope_key": "platform",
                "window_end": now,
                "data_status": "ready",
            },
            {
                "metric_code": "db_usage",
                "scope_key": "platform",
                "window_end": now,
                "data_status": "ready",
            },
        ]

    async def definitions(*_, **__):
        return [
            {
                "metric_code": "qa_success_rate",
                "metric_name": "问答成功率",
                "metric_domain": "qa",
                "unit": "percent",
                "formula": "成功数 / 总数",
                "status": "active",
                "version": 1,
            },
            {
                "metric_code": "db_usage",
                "metric_name": "数据库连接使用率",
                "metric_domain": "platform",
                "unit": "percent",
                "formula": "连接数 / 最大连接数",
                "status": "active",
                "version": 1,
            },
        ]

    async def events(*_, **__):
        return [
            {"source_code": "evaluation-1", "source_type": "evaluation", "status": "running"},
            {"source_code": "index-1", "source_type": "task", "status": "failed"},
            {"source_code": "api", "source_type": "service", "status": "healthy"},
        ]

    async def task_records(*_):
        return [
            {
                "task_key": "evaluation-1",
                "task_name": "evaluation-1",
                "task_type": "evaluation",
                "status": "running",
                "worker_code": "evaluation",
                "created_at": now,
            },
            {
                "task_key": "indexing-1",
                "task_name": "index-1",
                "task_type": "indexing",
                "status": "failed",
                "worker_code": "indexing",
                "created_at": now,
            },
        ]

    monkeypatch.setattr(monitoring.value_db, "list", metrics)
    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring, "_task_records", task_records)

    metric_result = await monitoring.metric_page(
        list_context,
        1,
        10,
        "问答",
        "qa",
        "current",
        "1h",
        "ready",
    )
    task_result = await monitoring.task_page(
        list_context, 1, 10, "evaluation", "evaluation", "running"
    )

    assert metric_result["total"] == 1
    assert metric_result["items"][0]["metric_code"] == "qa_success_rate"
    assert task_result["total"] == 1
    assert task_result["items"][0]["task_key"] == "evaluation-1"


@pytest.mark.asyncio
async def test_event_alert_and_audit_pages_apply_all_query_fields(list_context, monkeypatch):
    now = utils.utc_now()

    async def events(*_, **__):
        return [
            {
                "event_id": "event-index-1",
                "event_type": "task_failed",
                "source_type": "task",
                "source_code": "index-worker",
                "status": "failed",
                "trace_id": "trace-index-1",
                "occurred_at": now,
            },
            {
                "event_id": "event-evaluation-1",
                "event_type": "task_failed",
                "source_type": "evaluation_agent",
                "source_code": "evaluation",
                "status": "failed",
                "trace_id": "trace-evaluation-1",
                "occurred_at": now,
            },
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
        list_context,
        1,
        10,
        event_type="task_status",
        monitor_domain="task",
        resource_name="index",
        association_id="trace-index",
        time_range="1h",
        status="failed",
    )
    alert_result = await monitoring.alert_page(list_context, 1, 10, "firing", "critical", "index")
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
    assert event_result["items"][0]["event_type_name"] == "任务状态"
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


@pytest.mark.asyncio
async def test_overviews_use_real_full_range_data(list_context, monkeypatch):
    now = utils.utc_now()

    async def metrics(*_, **__):
        return [
            {
                "metric_code": "qa_success_rate",
                "scope_key": "qa",
                "tenant_id": None,
                "kb_id": None,
                "window_end": now,
                "data_status": "ready",
                "assessment_status": "warning",
            }
        ]

    async def definitions(*_, **__):
        return [
            {
                "metric_code": "qa_success_rate",
                "metric_name": "问答成功率",
                "metric_domain": "qa",
                "unit": "percent",
                "formula": "成功数 / 总数",
                "status": "active",
                "version": 1,
            }
        ]

    async def events(*_, **__):
        return [
            {
                "event_id": "task-1",
                "event_type": "task_running",
                "source_type": "task",
                "source_code": "index-task",
                "task_id": 1,
                "run_id": 1,
                "status": "running",
                "occurred_at": now,
            },
            {
                "event_id": "worker-1",
                "event_type": "worker_heartbeat",
                "source_type": "worker",
                "source_code": "worker-a",
                "status": "idle",
                "occurred_at": now - timedelta(seconds=10),
            },
        ]

    async def task_records(*_):
        return [
            {
                "task_key": "evaluation-1",
                "task_name": "评测运行 1",
                "task_type": "evaluation",
                "status": "running",
                "worker_code": "evaluation",
                "created_at": now,
                "wait_seconds": 10,
            }
        ]

    monkeypatch.setattr(monitoring.value_db, "list", metrics)
    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring, "_task_records", task_records)

    metric_result = await monitoring.metrics_overview(list_context)
    task_result = await monitoring.tasks_overview(list_context)
    event_result = await monitoring.events_overview(list_context)

    assert metric_result["status_distribution"]["warning"] == 1
    assert metric_result["trend"][0]["warning"] == 1
    assert task_result["total_count"] == 1
    assert event_result["total_count"] == 2
    assert event_result["source_distribution"] == [
        {
            "source_category": "task",
            "source_name": "任务运行",
            "count": 1,
            "color": "#5695f4",
        },
        {
            "source_category": "worker",
            "source_name": "Worker",
            "count": 1,
            "color": "#72c99b",
        },
        {
            "source_category": "alert",
            "source_name": "告警",
            "count": 0,
            "color": "#e5b347",
        },
        {
            "source_category": "collection",
            "source_name": "采集与依赖",
            "count": 0,
            "color": "#aeb9c8",
        },
    ]


@pytest.mark.asyncio
async def test_event_detail_returns_mapped_and_sanitized_context(list_context, monkeypatch):
    now = utils.utc_now()

    async def event(*_, **__):
        return {
            "event_id": "event-1",
            "event_type": "task_failed",
            "source_type": "task",
            "source_code": "document.indexing",
            "status": "failed",
            "occurred_at": now,
            "trace_id": "trace-1",
            "payload": {
                "error_category": "dependency_error",
                "question": "敏感问题",
                "nested": {"api_token": "secret", "retry_count": 2},
            },
            "data_status": "ready",
        }

    monkeypatch.setattr(monitoring.event_db, "get", event)

    result = await monitoring.event_detail(list_context, "event-1")

    assert result["event"]["event_type_name"] == "任务状态"
    assert result["event"]["resource_name"] == "文档索引"
    assert result["context"] == {
        "error_category": "dependency_error",
        "nested": {"retry_count": 2},
    }
    assert result["associations"]["trace_id"] == "trace-1"


def test_event_list_excludes_worker_idle_polling_events():
    events = [
        {"event_id": "idle-1", "event_type": "worker_idle"},
        {"event_id": "heartbeat-1", "event_type": "worker_heartbeat"},
    ]

    assert monitoring._visible_events(events) == [events[1]]


def test_metric_status_keeps_unassessed_ready_data_unknown():
    assert (
        monitoring._metric_status({"data_status": "ready", "assessment_status": "unknown"})
        == "unknown"
    )


def test_worker_views_keep_idle_healthy_and_count_claimed_tasks():
    now = utils.utc_now()
    workers = monitoring._worker_views(
        [
            {
                "event_type": "worker_heartbeat",
                "source_code": "evaluation",
                "occurred_at": now,
            },
            {
                "event_type": "worker_idle",
                "source_code": "evaluation",
                "occurred_at": now - timedelta(seconds=2),
            },
            {
                "event_type": "worker_heartbeat",
                "source_code": "indexing",
                "occurred_at": now,
            },
            {
                "event_type": "worker_task_claimed",
                "source_code": "indexing",
                "task_id": 42,
                "occurred_at": now - timedelta(seconds=1),
            },
        ]
    )

    assert workers[0]["status"] == "idle"
    assert workers[0]["capacity_status"] == "normal"
    assert workers[1]["status"] == "busy"
    assert workers[1]["consumed_count"] == 1


@pytest.mark.asyncio
async def test_task_detail_returns_read_only_real_evidence(list_context, monkeypatch):
    now = utils.utc_now()

    async def task_records(*_):
        return [
            {
                "task_key": "evaluation-9",
                "task_name": "评测运行 09",
                "task_type": "evaluation",
                "run_id": 9,
                "task_id": 7,
                "status": "running",
            }
        ]

    async def events(*_, **__):
        return [
            {
                "event_id": "evaluation-9-started",
                "event_type": "evaluation_run_started",
                "occurred_at": now,
            }
        ]

    monkeypatch.setattr(monitoring, "_task_records", task_records)
    monkeypatch.setattr(monitoring.event_db, "list", events)

    result = await monitoring.task_detail(list_context, "evaluation-9", "24h")

    assert result["task"]["task_key"] == "evaluation-9"
    assert result["evidence"][0]["event_type"] == "evaluation_run_started"
    assert result["data_status"] == "ready"


@pytest.mark.asyncio
async def test_metric_detail_returns_definition_without_fake_value(list_context, monkeypatch):
    async def definitions(*_, **__):
        return [
            {
                "metric_code": "qa_p95",
                "metric_name": "问答 P95",
                "metric_domain": "qa",
                "unit": "ms",
                "formula": "成功问答耗时第 95 百分位",
                "minimum_sample_count": 20,
                "status": "active",
                "version": 1,
            }
        ]

    async def empty(*_, **__):
        return []

    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.value_db, "list", empty)
    monkeypatch.setattr(monitoring.rule_db, "list", empty)
    monkeypatch.setattr(monitoring.alert_db, "list", empty)

    result = await monitoring.metric_detail(list_context, "qa_p95")

    assert result["metric"]["metric_name"] == "问答 P95"
    assert result["metric"]["metric_domain_name"] == "知识库问答"
    assert result["metric"]["metric_value"] is None
    assert result["metric"]["data_status"] == "empty"
    assert result["trend"] == []
