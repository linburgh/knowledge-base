from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.services import monitoring
from app.workers import monitoring_collect


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
