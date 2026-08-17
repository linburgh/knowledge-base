from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.common import utils
from app.core.common.auth import CurrentUser
from app.core.services.monitoring import mgr as monitoring
from app.db import api as db_api
from app.db.base import DB
from app.schemas.monitoring import MetricRuleRequest


def test_task_trend_separates_backlog_from_bucket_throughput():
    start_at = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    end_at = start_at + timedelta(minutes=25)
    tasks = [
        {
            "status": "pending",
            "created_at": start_at - timedelta(minutes=10),
            "started_at": None,
            "finished_at": None,
        },
        {
            "status": "completed",
            "created_at": start_at + timedelta(minutes=2),
            "started_at": start_at + timedelta(minutes=6),
            "finished_at": start_at + timedelta(minutes=12),
        },
        {
            "status": "failed",
            "created_at": start_at + timedelta(minutes=7),
            "started_at": start_at + timedelta(minutes=8),
            "finished_at": start_at + timedelta(minutes=16),
        },
        {
            "status": "timeout",
            "created_at": start_at + timedelta(minutes=14),
            "started_at": start_at + timedelta(minutes=15),
            "finished_at": start_at + timedelta(minutes=19),
        },
        {
            "status": "cancelled",
            "created_at": start_at + timedelta(minutes=20),
            "started_at": start_at + timedelta(minutes=21),
            "finished_at": start_at + timedelta(minutes=22),
        },
    ]

    trend = monitoring._task_trend(tasks, start_at, end_at)

    assert len(trend) == 5
    assert [point["pending_backlog"] for point in trend] == [2, 1, 1, 2, 1]
    assert [point["created"] for point in trend] == [1, 1, 1, 0, 1]
    assert [point["completed"] for point in trend] == [0, 0, 1, 0, 0]
    assert [point["failed"] for point in trend] == [0, 0, 0, 1, 0]
    assert [point["timeout"] for point in trend] == [0, 0, 0, 1, 0]
    assert [point["window_end"] for point in trend] == [
        start_at + timedelta(minutes=offset) for offset in (5, 10, 15, 20, 25)
    ]


def test_task_trend_does_not_create_empty_business_series():
    start_at = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)

    assert monitoring._task_trend([], start_at, start_at + timedelta(hours=1)) == []


@pytest.fixture
def list_context(monkeypatch):
    database = object()

    async def inject_db():
        DB.set(database)

    async def allow(*_):
        return {}

    async def scope(*_):
        return None

    async def rules(*_, **__):
        return []

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring, "tenant_scope", scope)
    monkeypatch.setattr(monitoring.rule_db, "list", rules)
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
                "metric_value": 1,
                "sample_count": 1,
            },
            {
                "metric_code": "db_usage",
                "scope_key": "platform",
                "window_end": now,
                "data_status": "ready",
                "metric_value": 0.1,
                "sample_count": 1,
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
            {
                "metric_code": "task_failure_rate",
                "severity": "critical",
                "status": "firing",
                "resource_code": "index-worker",
                "first_fired_at": now,
                "last_fired_at": now,
            },
            {
                "metric_code": "db_connection_usage",
                "severity": "critical",
                "status": "firing",
                "resource_code": "database",
                "first_fired_at": now,
                "last_fired_at": now,
            },
        ]

    async def definitions(*_, **__):
        return [
            {
                "metric_code": "task_failure_rate",
                "metric_name": "任务失败率",
                "metric_domain": "task",
                "status": "active",
                "version": 1,
            },
            {
                "metric_code": "db_connection_usage",
                "metric_name": "数据库连接使用率",
                "metric_domain": "platform",
                "status": "active",
                "version": 1,
            },
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

    async def users(*_, **__):
        return [
            {"id": 11, "username": "admin", "display_name": "林管理员"},
            {"id": 12, "username": "auditor", "display_name": "审计员"},
        ]

    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring.alert_db, "list", alerts)
    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.audit_log_db, "list", audits)
    monkeypatch.setattr(monitoring.user_db, "list", users)

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
    alert_result = await monitoring.alert_page(
        list_context,
        1,
        10,
        status="firing",
        severity="critical",
        monitor_domain="task",
        resource_name="index",
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
    assert event_result["items"][0]["event_type_name"] == "任务状态"
    assert alert_result["total"] == 1
    assert audit_result["total"] == 1


@pytest.mark.asyncio
async def test_rule_channel_and_policy_pages_return_backend_totals(list_context, monkeypatch):
    async def rules(*_, **__):
        return [
            {
                "id": 1,
                "metric_code": "qa_error_rate",
                "scope_type": "platform",
                "critical_threshold": 0.1,
                "enabled": True,
                "version": 1,
            },
            {
                "id": 2,
                "metric_code": "db_usage",
                "scope_type": "platform",
                "warning_threshold": 0.8,
                "enabled": True,
                "version": 1,
            },
        ]

    async def definitions(*_, **__):
        return [
            {
                "metric_code": "qa_error_rate",
                "metric_name": "问答错误率",
                "metric_domain": "qa",
                "status": "active",
                "version": 1,
            },
            {
                "metric_code": "db_usage",
                "metric_name": "数据库使用率",
                "metric_domain": "platform",
                "status": "active",
                "version": 1,
            },
        ]

    async def channels(*_, **__):
        return [
            {"id": 1, "channel_name": "平台 Webhook", "channel_type": "webhook"},
            {"id": 2, "channel_name": "站内通知", "channel_type": "in_app"},
        ]

    async def policies(*_, **__):
        return [
            {"id": 1, "policy_name": "严重告警通知", "event_types": []},
            {"id": 2, "policy_name": "普通告警通知", "event_types": []},
        ]

    async def records(*_, **__):
        return []

    async def links(*_, **__):
        return []

    monkeypatch.setattr(monitoring.rule_db, "list", rules)
    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.channel_db, "list", channels)
    monkeypatch.setattr(monitoring.policy_db, "list", policies)
    monkeypatch.setattr(monitoring.notification_record_db, "list", records)
    monkeypatch.setattr(monitoring.policy_channel_db, "list", links)

    rule_result = await monitoring.rule_page(list_context, 1, 10, rule_name="问答", enabled=True)
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
                "metric_value": 0.9,
                "sample_count": 10,
                "numerator": 9,
                "denominator": 10,
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
                "status": "failed",
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
    assert event_result["focus_event"] == {
        "event_id": "task-1",
        "event_type_name": "任务状态",
        "event_content": "index-task：失败",
        "monitor_domain_name": "异步任务",
        "resource_name": "index-task",
        "status": "failed",
        "status_name": "失败",
        "occurred_at": now,
        "related_alert_count": 0,
        "related_task_count": 1,
    }
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
async def test_events_overview_excludes_recovered_worker_stop_from_focus(list_context, monkeypatch):
    now = utils.utc_now()

    async def events(*_, **__):
        return [
            {
                "event_id": "notify-stopped",
                "event_type": "worker_stopped",
                "source_type": "worker",
                "source_code": "monitoring_notify",
                "status": "stopped",
                "occurred_at": now - timedelta(minutes=10),
            },
            {
                "event_id": "notify-started",
                "event_type": "worker_started",
                "source_type": "worker",
                "source_code": "monitoring_notify",
                "status": "started",
                "occurred_at": now - timedelta(minutes=9),
            },
            {
                "event_id": "notify-heartbeat",
                "event_type": "worker_heartbeat",
                "source_type": "worker",
                "source_code": "monitoring_notify",
                "status": "healthy",
                "occurred_at": now,
            },
        ]

    monkeypatch.setattr(monitoring.event_db, "list", events)

    result = await monitoring.events_overview(list_context)

    assert result["abnormal_count"] == 1
    assert result["focus_event"] is None
    assert result["conclusion"] == "运行正常"


@pytest.mark.asyncio
async def test_events_overview_translates_alert_key_to_tenant_name(list_context, monkeypatch):
    now = utils.utc_now()

    async def events(*_, **__):
        return [
            {
                "event_id": "alert-fired-1",
                "event_type": "alert_fired",
                "source_type": "alert",
                "source_code": "5:tenant:103",
                "tenant_id": 103,
                "status": "firing",
                "occurred_at": now,
                "payload": {"alert_id": 7, "metric_code": "qa_error_rate"},
            }
        ]

    async def tenant(*_, **__):
        return {"id": 103, "name": "演示租户"}

    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring.tenant_db, "get", tenant)

    result = await monitoring.events_overview(list_context)

    assert result["focus_event"]["resource_name"] == "演示租户"
    assert result["focus_event"]["event_content"] == "演示租户：触发中"
    assert "5:tenant:103" not in str(result["focus_event"])


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


@pytest.mark.asyncio
async def test_alert_overview_returns_lifecycle_trend_and_priority(list_context, monkeypatch):
    now = utils.utc_now()

    async def alerts(*_, **__):
        return [
            {
                "id": 1,
                "severity": "critical",
                "status": "acknowledged",
                "first_fired_at": now - timedelta(minutes=12),
                "last_fired_at": now,
                "acknowledged_at": now - timedelta(minutes=5),
            },
            {
                "id": 2,
                "severity": "warning",
                "status": "resolved",
                "first_fired_at": now - timedelta(minutes=20),
                "last_fired_at": now - timedelta(minutes=3),
                "resolved_at": now - timedelta(minutes=2),
            },
        ]

    monkeypatch.setattr(monitoring.alert_db, "list", alerts)

    result = await monitoring.alerts_overview(list_context)

    assert result["conclusion"] == "需要处理"
    assert result["unresolved_count"] == 1
    assert result["lifecycle"]["acknowledged"] == 1
    assert result["lifecycle"]["resolved"] == 1
    assert len(result["trend"]) == 13
    assert [item["severity_name"] for item in result["severity_distribution"]] == [
        "严重",
        "警告",
        "提示",
    ]


@pytest.mark.asyncio
async def test_alert_page_keeps_old_unresolved_alerts_visible(list_context, monkeypatch):
    now = utils.utc_now()

    async def alerts(*_, **__):
        return [
            {
                "id": 1,
                "metric_code": "task_success_rate",
                "alert_title": "历史未恢复告警",
                "severity": "critical",
                "status": "firing",
                "first_fired_at": now - timedelta(days=7),
                "last_fired_at": now - timedelta(days=6),
            },
            {
                "id": 2,
                "metric_code": "task_success_rate",
                "alert_title": "历史已恢复告警",
                "severity": "warning",
                "status": "resolved",
                "first_fired_at": now - timedelta(days=7),
                "last_fired_at": now - timedelta(days=6),
                "resolved_at": now - timedelta(days=6),
            },
        ]

    async def definitions(*_, **__):
        return []

    monkeypatch.setattr(monitoring.alert_db, "list", alerts)
    monkeypatch.setattr(monitoring.definition_db, "list", definitions)

    result = await monitoring.alert_page(list_context, 1, 20, time_range="1h")

    assert result["total"] == 1
    assert result["items"][0]["status"] == "firing"


@pytest.mark.asyncio
async def test_notification_contract_joins_channel_policy_and_alert(list_context, monkeypatch):
    now = utils.utc_now()

    async def channels(*_, **__):
        return [
            {
                "id": 1,
                "channel_name": "平台 Webhook",
                "channel_type": "webhook",
                "status": "enabled",
            }
        ]

    async def policies(*_, **__):
        return [
            {
                "id": 2,
                "policy_name": "严重告警通知",
                "severity": "critical",
                "scope": {"scope_type": "platform"},
                "status": "enabled",
            }
        ]

    async def alerts(*_, **__):
        return [{"id": 3, "severity": "critical"}]

    async def records(*_, **__):
        return [
            {
                "id": 4,
                "channel_id": 1,
                "policy_id": 2,
                "alert_id": 3,
                "event_type": "firing",
                "status": "failed",
                "failure_category": "timeout",
                "retry_count": 1,
                "created_at": now,
            }
        ]

    monkeypatch.setattr(monitoring.channel_db, "list", channels)
    monkeypatch.setattr(monitoring.policy_db, "list", policies)
    monkeypatch.setattr(monitoring.alert_db, "list", alerts)
    monkeypatch.setattr(monitoring.notification_record_db, "list", records)

    overview = await monitoring.notifications_overview(list_context)
    page = await monitoring.notification_record_page(
        list_context,
        1,
        10,
        channel_type="webhook",
        status="failed",
        severity="critical",
    )

    assert overview["failed_count"] == 1
    assert page["total"] == 1
    assert page["items"][0]["channel_name"] == "平台 Webhook"
    assert page["items"][0]["policy_name"] == "严重告警通知"
    assert page["items"][0]["failure_summary"] == "timeout"


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
    captured_alert_filters = {}

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

    async def alerts(*_, **filters):
        captured_alert_filters.update(filters)
        return []

    monkeypatch.setattr(monitoring.definition_db, "list", definitions)
    monkeypatch.setattr(monitoring.value_db, "list", empty)
    monkeypatch.setattr(monitoring.rule_db, "list", empty)
    monkeypatch.setattr(monitoring.alert_db, "list", alerts)

    result = await monitoring.metric_detail(list_context, "qa_p95")

    assert result["metric"]["metric_name"] == "问答 P95"
    assert result["metric"]["metric_domain_name"] == "知识库问答"
    assert result["metric"]["metric_value"] is None
    assert result["metric"]["data_status"] == "empty"
    assert result["trend"] == []
    assert captured_alert_filters == {
        "resource_code": "platform",
        "metric_code": "qa_p95",
    }


@pytest.mark.asyncio
async def test_rule_update_and_toggle_create_audited_versions(monkeypatch):
    class TransactionDatabase:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def transaction(self):
            return self

    database = TransactionDatabase()
    rules = [
        {
            "id": 1,
            "metric_code": "qa_error_rate",
            "scope_type": "platform",
            "warning_threshold": 0.1,
            "critical_threshold": 0.2,
            "recovery_threshold": 0.05,
            "minimum_sample_count": 10,
            "consecutive_periods": 3,
            "window_seconds": 300,
            "trigger_type": "threshold",
            "recovery_periods": 2,
            "enabled": True,
            "version": 1,
        }
    ]
    audits = []

    async def inject_db():
        DB.set(database)

    async def allow(*_):
        return {}

    async def list_rules(*_, **filters):
        return [
            row for row in rules if all(row.get(key) == value for key, value in filters.items())
        ]

    async def get_rule(*_, **filters):
        return next(
            (row for row in rules if all(row.get(key) == value for key, value in filters.items())),
            None,
        )

    async def update_rule(_, values, **filters):
        target = await get_rule(_, **filters)
        target.update(values)

    async def insert_rule(_, **values):
        rule_id = len(rules) + 1
        rules.append({"id": rule_id, **values})
        return rule_id

    async def audit(*_, **values):
        audits.append(values)

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring.rule_db, "list", list_rules)
    monkeypatch.setattr(monitoring.rule_db, "get", get_rule)
    monkeypatch.setattr(monitoring.rule_db, "update_", update_rule)
    monkeypatch.setattr(monitoring.rule_db, "insert_", insert_rule)
    monkeypatch.setattr(monitoring.audit_service, "record", audit)

    user = CurrentUser(user_id="11")
    payload = MetricRuleRequest(
        metric_code="qa_error_rate",
        warning_threshold=0.12,
        critical_threshold=0.25,
        recovery_threshold=0.05,
        minimum_sample_count=10,
        consecutive_periods=3,
        recovery_periods=2,
    )
    updated = await monitoring.update_rule(1, payload, user)
    toggled = await monitoring.toggle_rule(updated["id"], user)

    assert updated["version"] == 2
    assert updated["warning_threshold"] == 0.12
    assert toggled["version"] == 3
    assert toggled["enabled"] is False
    assert rules[0]["enabled"] is False
    assert {audit["action"] for audit in audits} == {"monitor_rule_created"}
