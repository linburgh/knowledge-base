from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import monitoring as monitoring_api
from app.core.common import auth
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services.monitoring import mgr as monitoring
from app.db import api as db_api
from app.db.base import DB


class FakeDatabase:
    pass


@pytest.mark.parametrize(
    ("time_range", "duration"),
    (
        ("15m", monitoring.timedelta(minutes=15)),
        ("1h", monitoring.timedelta(hours=1)),
        ("6h", monitoring.timedelta(hours=6)),
        ("24h", monitoring.timedelta(hours=24)),
        ("7d", monitoring.timedelta(days=7)),
    ),
)
def test_overview_window_supports_frontend_ranges(
    time_range,
    duration,
    monkeypatch,
):
    now = datetime(2026, 7, 31, 5, 0, tzinfo=UTC)
    monkeypatch.setattr(monitoring.utils, "utc_now", lambda: now)

    start_at, end_at = monitoring._overview_window(time_range)

    assert start_at == now - duration
    assert end_at == now


def test_runtime_timeline_returns_backend_names_and_risk_first_top_five(monkeypatch):
    now = datetime(2026, 7, 31, 5, 0, tzinfo=UTC)
    monkeypatch.setattr(monitoring.utils, "utc_now", lambda: now)
    snapshots = [
        {
            "resource_type": "dependency",
            "resource_code": resource_code,
            "status": status,
            "updated_at": now,
        }
        for resource_code, status in (
            ("api-service", "healthy"),
            ("database", "healthy"),
            ("llm-service", "healthy"),
            ("embedding-service", "healthy"),
            ("rerank-service", "failed"),
            ("vector-service", "warning"),
            ("storage-service", "healthy"),
            ("unknown-service", "unknown"),
        )
    ]

    result = monitoring._runtime_timeline(
        snapshots,
        [],
        now - monitoring.timedelta(hours=1),
        now,
        "1h",
    )

    assert len(result) == 5
    assert [item["resource_code"] for item in result[:3]] == [
        "rerank-service",
        "vector-service",
        "unknown-service",
    ]
    assert result[0]["resource_name"] == "重排服务"
    assert result[1]["resource_name"] == "向量服务"
    assert result[2]["resource_name"] == "其他服务"
    assert all(len(item["resource_name"]) == 4 for item in result)


def test_resource_capacity_keeps_required_four_and_does_not_fake_missing_quota():
    now = datetime.now(UTC)
    snapshots = [
        {
            "resource_type": "capacity",
            "resource_code": "database-capacity",
            "status": "healthy",
            "status_value": {
                "name": "数据库连接",
                "capacity_kind": "database_instance",
                "usage": 10,
                "used": 10,
                "capacity": 100,
                "threshold": 80,
            },
            "updated_at": now,
        },
        {
            "resource_type": "capacity",
            "resource_code": "task-queue-capacity",
            "status": "healthy",
            "status_value": {
                "name": "队列容量",
                "capacity_kind": "task_queue",
                "usage": 3,
                "used": 3,
                "capacity": 100,
                "threshold": 80,
            },
            "updated_at": now,
        },
        {
            "resource_type": "capacity",
            "resource_code": "file-storage-capacity",
            "status": "unknown",
            "status_value": {
                "name": "文件存储",
                "capacity_kind": "file_storage",
                "usage": None,
                "used": 1024,
                "capacity": None,
                "threshold": 80,
            },
            "updated_at": now,
        },
        {
            "resource_type": "capacity",
            "resource_code": "vector-storage-capacity",
            "status": "unknown",
            "status_value": {
                "name": "向量存储",
                "capacity_kind": "vector_storage",
                "usage": None,
                "used": 2048,
                "capacity": None,
                "threshold": 80,
            },
            "updated_at": now,
        },
        {
            "resource_type": "capacity",
            "resource_code": "platform-capacity",
            "status": "healthy",
            "status_value": {"name": "本地暂存空间", "usage": 10},
            "updated_at": now,
        },
    ]

    result = monitoring._resource_capacity(snapshots)

    assert [item["resource_name"] for item in result] == [
        "数据库连接",
        "队列容量",
        "文件存储",
        "向量存储",
    ]
    assert result[2]["usage"] is None
    assert result[2]["used"] == 1024
    assert result[2]["data_status"] == "empty"
    assert result[3]["resource_name"] == "向量存储"


def test_resource_capacity_keeps_failed_required_item():
    result = monitoring._resource_capacity(
        [
            {
                "resource_type": "capacity",
                "resource_code": "file-storage-capacity",
                "status": "failed",
                "status_value": {"latency_ms": 10},
                "updated_at": datetime.now(UTC),
            }
        ]
    )

    assert result == [
        {
            "resource_code": "file-storage-capacity",
            "resource_name": "文件存储",
            "usage": None,
            "threshold": None,
            "unit": "%",
            "used": None,
            "capacity": None,
            "data_status": "error",
        }
    ]


def test_alert_status_overview_uses_all_alerts_and_limits_recent_changes():
    base_time = datetime(2026, 7, 31, 5, 0, tzinfo=UTC)
    alerts = [
        {
            "id": index,
            "status": status,
            "last_fired_at": base_time + monitoring.timedelta(minutes=index),
            "acknowledged_at": (
                base_time + monitoring.timedelta(minutes=index) if status == "acknowledged" else None
            ),
            "resolved_at": (
                base_time + monitoring.timedelta(minutes=index) if status == "resolved" else None
            ),
            "closed_at": (
                base_time + monitoring.timedelta(minutes=index) if status == "closed" else None
            ),
        }
        for index, status in enumerate(
            ("firing", "acknowledged", "resolved", "closed", "closed"),
            start=1,
        )
    ]

    summary = monitoring._alert_status_summary(alerts)
    recent = monitoring._recent_alert_changes(alerts)

    assert summary == {"firing": 1, "acknowledged": 1, "resolved": 1, "closed": 2}
    assert [item["id"] for item in recent] == [5, 4, 3]
    assert [item["latest_change_name"] for item in recent] == [
        "告警关闭",
        "告警关闭",
        "告警恢复",
    ]


@pytest.mark.parametrize(
    ("time_range", "duration", "expected_interval", "expected_count"),
    (
        ("15m", monitoring.timedelta(minutes=15), 5, 4),
        ("1h", monitoring.timedelta(hours=1), 5, 13),
        ("6h", monitoring.timedelta(hours=6), 30, 13),
        ("24h", monitoring.timedelta(hours=24), 120, 13),
        ("7d", monitoring.timedelta(days=7), 720, 15),
    ),
)
def test_runtime_timeline_uses_window_granularity_and_iso_time(
    time_range,
    duration,
    expected_interval,
    expected_count,
):
    end_at = datetime(2026, 7, 31, 6, 37, tzinfo=UTC)
    snapshot = {
        "resource_type": "service",
        "resource_code": "api-service",
        "status": "healthy",
        "checked_at": end_at,
        "updated_at": end_at,
    }

    result = monitoring._runtime_timeline(
        [snapshot],
        [],
        end_at - duration,
        end_at,
        time_range,
    )
    timeline = result[0]["timeline"]

    assert len(timeline) == expected_count
    assert datetime.fromisoformat(timeline[0]["time"]).tzinfo is not None
    assert (
        datetime.fromisoformat(timeline[1]["time"]) - datetime.fromisoformat(timeline[0]["time"])
    ) == monitoring.timedelta(minutes=expected_interval)
    assert timeline[-2]["status"] == "unknown"
    assert timeline[-1]["status"] == "healthy"


def test_runtime_timeline_does_not_backfill_current_status():
    end_at = datetime(2026, 7, 31, 6, 37, tzinfo=UTC)
    event_at = end_at - monitoring.timedelta(minutes=10)
    snapshot = {
        "resource_type": "dependency",
        "resource_code": "rerank-service",
        "status": "healthy",
        "checked_at": end_at,
        "updated_at": end_at,
    }
    events = [
        {
            "source_code": "rerank-service",
            "status": "failed",
            "occurred_at": event_at,
        }
    ]

    result = monitoring._runtime_timeline(
        [snapshot],
        events,
        end_at - monitoring.timedelta(hours=1),
        end_at,
        "1h",
    )
    statuses = [item["status"] for item in result[0]["timeline"]]

    assert statuses.count("failed") == 1
    assert statuses.count("healthy") == 1
    assert statuses.count("unknown") == 11


@pytest.fixture
def overview_context(monkeypatch):
    database = FakeDatabase()

    async def inject_db():
        DB.set(database)

    async def allow(*_):
        return {}

    async def scope(*_):
        return 10

    monkeypatch.setattr(db_api, "inject_db", inject_db)
    monkeypatch.setattr(monitoring, "require_monitoring_access", allow)
    monkeypatch.setattr(monitoring, "tenant_scope", scope)
    return CurrentUser(user_id="11", tenant_id=10)


@pytest.mark.asyncio
async def test_overview_returns_empty_status_for_each_section(
    overview_context,
    monkeypatch,
):
    async def empty_list(*_, **__):
        return []

    monkeypatch.setattr(monitoring.event_db, "list", empty_list)
    monkeypatch.setattr(monitoring.alert_db, "list", empty_list)
    monkeypatch.setattr(monitoring.snapshot_db, "list", empty_list)

    result = await monitoring.overview(overview_context)

    assert result["data_status"] == "empty"
    assert set(result["section_statuses"].values()) == {"empty"}
    assert result["section_errors"] == {}


@pytest.mark.asyncio
async def test_overview_keeps_snapshot_modules_when_event_query_fails(
    overview_context,
    monkeypatch,
):
    now = datetime.now(UTC)

    async def failed_events(*_, **__):
        raise RuntimeError("database connection detail must not be returned")

    async def empty_alerts(*_, **__):
        return []

    async def snapshots(*_, **__):
        return [
            {
                "resource_type": "service",
                "resource_code": "api-service",
                "status": "healthy",
                "status_value": {"name": "API 服务", "usage": 42},
                "updated_at": now,
            },
            {
                "resource_type": "capacity",
                "resource_code": "database-capacity",
                "status": "healthy",
                "status_value": {
                    "name": "数据库连接",
                    "capacity_kind": "database_instance",
                    "usage": 10,
                    "used": 10,
                    "capacity": 100,
                    "unit": "%",
                    "threshold": 80,
                },
                "updated_at": now,
            },
        ]

    monkeypatch.setattr(monitoring.event_db, "list", failed_events)
    monkeypatch.setattr(monitoring.alert_db, "list", empty_alerts)
    monkeypatch.setattr(monitoring.snapshot_db, "list", snapshots)

    result = await monitoring.overview(overview_context)

    assert result["data_status"] == "partial"
    assert result["runtime_status"]
    assert result["runtime_status"][0]["resource_name"] == "接口服务"
    assert result["resource_capacity"]
    assert result["section_statuses"] == {
        "unresolved_alerts": "empty",
        "runtime_status": "partial",
        "business_status": "error",
        "alert_status_trend": "empty",
        "resource_capacity": "ready",
        "propagation": "error",
    }
    assert result["section_errors"]["runtime_status"] == ("事件数据查询失败，当前仅展示运行快照")
    assert "database connection detail" not in str(result["section_errors"])


@pytest.mark.asyncio
async def test_overview_returns_independent_business_and_capacity_times(
    overview_context,
    monkeypatch,
):
    business_time = datetime(2026, 7, 31, 5, 1, tzinfo=UTC)
    capacity_time = datetime(2026, 7, 31, 5, 2, tzinfo=UTC)

    async def events(*_, **__):
        return [
            {
                "source_type": "qa",
                "status": "completed",
                "occurred_at": business_time,
            }
        ]

    async def empty_alerts(*_, **__):
        return []

    async def snapshots(*_, **__):
        return [
            {
                "resource_type": "capacity",
                "resource_code": "database-capacity",
                "status": "healthy",
                "status_value": {
                    "usage": 10,
                    "used": 10,
                    "capacity": 100,
                    "threshold": 80,
                },
                "checked_at": capacity_time,
                "updated_at": capacity_time,
            }
        ]

    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring.alert_db, "list", empty_alerts)
    monkeypatch.setattr(monitoring.snapshot_db, "list", snapshots)

    result = await monitoring.overview(overview_context)

    assert result["business_updated_at"] == business_time
    assert result["resource_capacity_updated_at"] == capacity_time


@pytest.mark.asyncio
async def test_overview_converges_all_source_failures(
    overview_context,
    monkeypatch,
):
    async def failed_list(*_, **__):
        raise RuntimeError("sensitive failure")

    monkeypatch.setattr(monitoring.event_db, "list", failed_list)
    monkeypatch.setattr(monitoring.alert_db, "list", failed_list)
    monkeypatch.setattr(monitoring.snapshot_db, "list", failed_list)

    result = await monitoring.overview(overview_context)

    assert result["data_status"] == "error"
    assert set(result["section_statuses"].values()) == {"error"}
    assert "sensitive failure" not in str(result["section_errors"])


@pytest.mark.asyncio
async def test_overview_http_contract_returns_module_states(
    overview_context,
    monkeypatch,
):
    async def empty_list(*_, **__):
        return []

    async def current_user():
        return overview_context

    monkeypatch.setattr(monitoring.event_db, "list", empty_list)
    monkeypatch.setattr(monitoring.alert_db, "list", empty_list)
    monkeypatch.setattr(monitoring.snapshot_db, "list", empty_list)

    app = FastAPI()
    app.include_router(monitoring_api.router, prefix="/api/v1/monitoring")
    app.dependency_overrides[auth.get_current_user] = current_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/monitoring/overview",
            params={"scope_key": "platform", "time_range": "1h"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"] == "empty"
    assert payload["section_statuses"]["propagation"] == "empty"
    assert payload["section_errors"] == {}


@pytest.mark.asyncio
async def test_overview_applies_selected_time_window(
    overview_context,
    monkeypatch,
):
    captured = {}
    now = datetime(2026, 7, 31, 5, 0, tzinfo=UTC)

    async def event_list(*_, **filters):
        captured["events"] = filters
        return []

    async def alert_list(*_, **filters):
        captured["alerts"] = filters
        return []

    async def snapshot_list(*_, **filters):
        captured["snapshots"] = filters
        return []

    monkeypatch.setattr(monitoring.utils, "utc_now", lambda: now)
    monkeypatch.setattr(monitoring.event_db, "list", event_list)
    monkeypatch.setattr(monitoring.alert_db, "list", alert_list)
    monkeypatch.setattr(monitoring.snapshot_db, "list", snapshot_list)

    result = await monitoring.overview(overview_context, "15m", "platform")

    assert captured["events"]["occurred_at__gte"] == now - monitoring.timedelta(minutes=15)
    assert captured["events"]["occurred_at__lte"] == now
    assert "last_fired_at__gte" not in captured["alerts"]
    assert captured["snapshots"]["updated_at__gte"] == now - monitoring.timedelta(minutes=15)
    assert result["time_range"] == "15m"
    assert result["window_end"] == now


@pytest.mark.asyncio
async def test_overview_recognizes_real_agent_source_types_and_normalizes_propagation_domains(
    overview_context,
    monkeypatch,
):
    now = datetime(2026, 7, 31, 5, 0, tzinfo=UTC)

    async def events(*_, **__):
        return [
            {
                "event_id": "qa-1",
                "event_type": "qa_completed",
                "source_type": "knowledge_agent",
                "status": "completed",
                "occurred_at": now,
                "duration_ms": 200,
            },
            {
                "event_id": "evaluation-1",
                "event_type": "evaluation_run_started",
                "source_type": "evaluation_agent",
                "status": "running",
                "occurred_at": now,
            },
            {
                "event_id": "alert-1",
                "event_type": "alert_fired",
                "source_type": "alert",
                "status": "firing",
                "occurred_at": now,
            },
        ]

    async def empty_list(*_, **__):
        return []

    monkeypatch.setattr(monitoring.utils, "utc_now", lambda: now)
    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring.alert_db, "list", empty_list)
    monkeypatch.setattr(monitoring.snapshot_db, "list", empty_list)

    result = await monitoring.overview(overview_context)

    business = {item["code"]: item for item in result["business_status"]}
    assert business["qa"]["value"] == 1
    assert business["evaluation"]["value"] == 1
    assert {item["domain"] for item in result["propagation"]} == {
        "qa",
        "evaluation",
        "alert",
    }


@pytest.mark.asyncio
async def test_overview_keeps_worker_heartbeat_but_ignores_database_and_probe_noise(
    overview_context,
    monkeypatch,
):
    now = datetime(2026, 7, 31, 5, 0, tzinfo=UTC)

    async def events(*_, **__):
        return [
            {
                "event_id": "db-1",
                "event_type": "db_operation_completed",
                "source_type": "database",
                "status": "completed",
                "occurred_at": now,
            },
            {
                "event_id": "probe-1",
                "event_type": "rerank_probe_failed",
                "source_type": "probe",
                "status": "failed",
                "occurred_at": now,
            },
            {
                "event_id": "worker-1",
                "event_type": "worker_heartbeat",
                "source_type": "worker",
                "status": "healthy",
                "occurred_at": now,
            },
        ]

    async def empty_list(*_, **__):
        return []

    monkeypatch.setattr(monitoring.utils, "utc_now", lambda: now)
    monkeypatch.setattr(monitoring.event_db, "list", events)
    monkeypatch.setattr(monitoring.alert_db, "list", empty_list)
    monkeypatch.setattr(monitoring.snapshot_db, "list", empty_list)

    result = await monitoring.overview(overview_context)

    assert len(result["propagation"]) == 1
    assert result["propagation"][0]["id"] == "worker-1"
    assert result["propagation"][0]["domain"] == "index"
    assert result["propagation"][0]["status"] == "healthy"
    assert result["section_statuses"]["propagation"] == "ready"


@pytest.mark.asyncio
async def test_overview_projects_normal_snapshots_into_runtime_chain(
    overview_context,
    monkeypatch,
):
    now = datetime(2026, 7, 31, 5, 0, tzinfo=UTC)

    async def empty_list(*_, **__):
        return []

    async def snapshots(*_, **__):
        return [
            {
                "id": 1,
                "resource_type": "service",
                "resource_code": "api-service",
                "status": "healthy",
                "checked_at": now,
                "updated_at": now,
            },
            {
                "id": 2,
                "resource_type": "capacity",
                "resource_code": "database-capacity",
                "status": "healthy",
                "updated_at": now,
            },
        ]

    monkeypatch.setattr(monitoring.utils, "utc_now", lambda: now)
    monkeypatch.setattr(monitoring.event_db, "list", empty_list)
    monkeypatch.setattr(monitoring.alert_db, "list", empty_list)
    monkeypatch.setattr(monitoring.snapshot_db, "list", snapshots)

    result = await monitoring.overview(overview_context)

    assert result["propagation"] == [
        {
            "id": "snapshot-1",
            "domain": "platform",
            "title": "接口服务探测",
            "status": "healthy",
            "occurred_at": now,
            "trace_id": None,
        }
    ]
    assert result["section_statuses"]["propagation"] == "ready"


@pytest.mark.asyncio
async def test_overview_rejects_invalid_query_range(
    overview_context,
):
    with pytest.raises(BusiException, match="time_range"):
        await monitoring.overview(overview_context, "all", "platform")

    with pytest.raises(BusiException, match="scope_key"):
        await monitoring.overview(overview_context, "1h", "all")
