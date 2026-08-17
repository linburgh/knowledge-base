from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.common.auth import CurrentUser
from app.core.services.monitoring import mgr as monitoring
from app.db import api as db_api
from app.db.base import DB
from app.workers.monitoring import collect as monitoring_collect


def test_monitoring_workers_use_domain_package_without_repeated_prefix():
    workers_dir = Path(__file__).parents[1] / "app" / "workers"
    monitoring_dir = workers_dir / "monitoring"

    assert {path.name for path in monitoring_dir.glob("*.py")} == {
        "__init__.py",
        "aggregate.py",
        "collect.py",
        "notify.py",
    }
    assert not list(workers_dir.glob("monitoring_*.py"))


@pytest.mark.asyncio
async def test_database_capacity_uses_database_instance_and_keeps_pool_details(monkeypatch):
    async def instance_stats(_db):
        return {
            "used": 18,
            "capacity": 100,
            "current_database_connections": 12,
            "active_connections": 4,
            "idle_connections": 14,
            "reserved_connections": 3,
            "pool_used": 2,
            "pool_size": 10,
            "pool_idle": 8,
            "pool_capacity": 10,
        }

    monkeypatch.setattr(monitoring_collect, "database_instance_stats", instance_stats)
    token = monitoring_collect.DB.set(object())
    try:
        result = await monitoring_collect._probe_database_capacity(
            {"warning_threshold": 80, "critical_threshold": 95},
            3,
        )
    finally:
        monitoring_collect.DB.reset(token)

    assert result["name"] == "数据库连接"
    assert result["capacity_kind"] == "database_instance"
    assert result["used"] == 18
    assert result["capacity"] == 100
    assert result["usage"] == 18
    assert result["pool_capacity"] == 10
    assert result["pool_used"] == 2


def test_collection_timeline_groups_targets_by_domain_and_five_minute_bucket():
    end_at = datetime(2026, 7, 31, 2, 0, tzinfo=UTC)
    start_at = end_at - timedelta(minutes=10)
    targets = [
        {
            "target_code": "knowledge.qa",
            "target_type": "method",
            "target_locator": {},
        },
        {
            "target_code": "probe.rerank",
            "target_type": "probe",
            "target_locator": {
                "resource_code": "rerank-service",
                "interval_seconds": 60,
            },
        },
    ]
    events = [
        {
            "source_code": "rerank-service",
            "status": "failed",
            "data_status": "ready",
            "occurred_at": end_at - timedelta(minutes=1),
        },
        {
            "source_code": "knowledge.qa",
            "status": "completed",
            "data_status": "ready",
            "occurred_at": end_at - timedelta(minutes=2),
        },
    ]

    trend, heatmap = monitoring._collection_timeline(targets, events, start_at, end_at)

    assert len(trend) == 3
    assert {item["domain_name"] for item in heatmap} == {"问答链路", "外部依赖"}
    latest = [item for item in heatmap if item["time"] == end_at]
    assert {item["domain_name"]: item["status"] for item in latest} == {
        "问答链路": "ready",
        "外部依赖": "error",
    }


def test_collection_target_view_exposes_backend_labels_and_latest_fact():
    now = datetime(2026, 7, 31, 2, 0, tzinfo=UTC)
    target = {
        "id": 1,
        "target_code": "capacity.database",
        "target_name": "数据库连接容量",
        "target_type": "probe",
        "target_locator": {
            "resource_code": "database-capacity",
            "interval_seconds": 60,
        },
    }
    event = {
        "source_code": "database-capacity",
        "status": "healthy",
        "data_status": "ready",
        "duration_ms": 12,
        "occurred_at": now - timedelta(seconds=30),
    }

    result = monitoring._collection_target_view(target, [event], now)

    assert result["target_type_name"] == "容量探针"
    assert result["data_status"] == "ready"
    assert result["data_status_name"] == "正常"
    assert result["last_collected_at"] == event["occurred_at"]
    assert result["duration_ms"] == 12


def test_collection_target_matches_worker_event_by_configured_action():
    now = datetime(2026, 7, 31, 2, 0, tzinfo=UTC)
    target = {
        "id": 1,
        "target_code": "worker.lifecycle",
        "target_name": "Worker 生命周期",
        "target_type": "worker",
        "target_locator": {},
    }
    event = {
        "source_code": "indexing",
        "event_type": "worker_idle",
        "status": "idle",
        "data_status": "ready",
        "occurred_at": now - timedelta(seconds=10),
    }
    action_event_types = monitoring._collection_action_event_types(
        [{"target_code": "worker.lifecycle", "event_type": "worker_idle"}]
    )

    result = monitoring._collection_target_view(
        target,
        [event],
        now,
        action_event_types,
    )

    assert result["data_status"] == "ready"
    assert result["last_collected_at"] == event["occurred_at"]


def test_event_driven_target_without_business_run_waits_for_trigger():
    now = datetime(2026, 7, 31, 2, 0, tzinfo=UTC)
    target = {
        "id": 1,
        "target_code": "evaluation.run",
        "target_name": "自主评测运行",
        "target_type": "method",
        "target_locator": {},
    }

    result = monitoring._collection_target_view(target, [], now)

    assert result["data_status"] == "idle"
    assert result["data_status_name"] == "等待触发"
    assert result["last_collected_at"] is None


def test_collected_business_failure_does_not_become_collection_failure():
    now = datetime(2026, 7, 31, 2, 0, tzinfo=UTC)
    target = {
        "id": 1,
        "target_code": "api.http",
        "target_name": "API 请求采集",
        "target_type": "api",
        "target_locator": {},
    }
    event = {
        "source_code": "api.http",
        "event_type": "http_request_failed",
        "status": "failed",
        "data_status": "ready",
        "occurred_at": now - timedelta(seconds=5),
    }

    result = monitoring._collection_target_view(target, [event], now)

    assert result["data_status"] == "ready"
    assert result["data_status_name"] == "正常"


@pytest.mark.asyncio
async def test_collection_overview_only_counts_enabled_targets(monkeypatch):
    database = object()
    captured_target_filters = {}

    async def inject_db():
        DB.set(database)

    async def allow(*_):
        return {}

    async def scope(*_):
        return None

    async def events(*_, **__):
        return []

    async def targets(*_, **filters):
        captured_target_filters.update(filters)
        return []

    async def actions(*_, **filters):
        assert filters == {"enabled": True}
        return []

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring, "tenant_scope", scope)
    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring.gather_target_db, "list", targets)
    monkeypatch.setattr(monitoring.gather_action_db, "list", actions)

    result = await monitoring.collection_overview(CurrentUser(user_id="11"))

    assert captured_target_filters == {"enabled": True}
    assert result["target_count"] == 0
    assert result["data_status"] == "empty"
