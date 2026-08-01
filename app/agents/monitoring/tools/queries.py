from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.agents.monitoring.tools.registry import MonitoringToolRegistry
from app.db import (
    monitor_alert as alert_db,
)
from app.db import (
    monitor_event as event_db,
)
from app.db import (
    monitor_metric_definition as definition_db,
)
from app.db import (
    monitor_metric_value as value_db,
)
from app.db import (
    monitor_state_snapshot as snapshot_db,
)
from app.db.base import DB

_STATUS_NAMES = {
    "healthy": "正常",
    "normal": "正常",
    "ok": "正常",
    "warning": "预警",
    "degraded": "降级",
    "stale": "数据过期",
    "failed": "失败",
    "error": "异常",
    "firing": "告警中",
    "acknowledged": "已确认",
    "resolved": "已恢复",
    "closed": "已关闭",
    "completed": "已完成",
    "running": "运行中",
}


def _scope_filter(scope: int | None) -> dict[str, Any]:
    return {"tenant_id": scope} if scope is not None else {}


def _in_window(value: datetime | None, start: datetime, end: datetime) -> bool:
    return value is not None and start <= value < end


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _result(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": items[:50], "data_status": "ready" if items else "empty"}


def build_monitoring_tool_registry(*, scope: int | None) -> MonitoringToolRegistry:
    registry = MonitoringToolRegistry()

    async def query_health_snapshots(
        *, window_start: datetime, window_end: datetime, scope_key: str
    ) -> dict[str, Any]:
        del scope_key
        rows = await snapshot_db.list(
            DB.get(),
            **_scope_filter(scope),
            checked_at__gte=window_start,
        )
        items = []
        for row in rows:
            if not _in_window(row.get("checked_at"), window_start, window_end):
                continue
            status = str(row.get("status") or "unknown")
            items.append(
                {
                    "id": f"health-{row['id']}",
                    "evidence_type": "health",
                    "evidence_type_name": "健康状态",
                    "title": f"{row.get('resource_type')} · {row.get('resource_code')}",
                    "summary": f"状态：{_STATUS_NAMES.get(status, status)}",
                    "evidence_level": "direct",
                    "evidence_level_name": "直接证据",
                    "occurred_at": row.get("checked_at"),
                    "target_id": str(row.get("resource_code") or row["id"]),
                    "status": status,
                    "expires_at": row.get("expires_at"),
                }
            )
        return _result(items)

    async def query_alerts(
        *, window_start: datetime, window_end: datetime, scope_key: str
    ) -> dict[str, Any]:
        del scope_key
        rows = await alert_db.list(DB.get(), **_scope_filter(scope))
        items = []
        for row in rows:
            status = str(row.get("status") or "unknown")
            effective_end = (
                window_end
                if status in {"firing", "acknowledged"}
                else row.get("closed_at") or row.get("resolved_at") or row.get("last_fired_at")
            )
            if row.get("first_fired_at") is None or effective_end is None:
                continue
            if row["first_fired_at"] >= window_end or effective_end < window_start:
                continue
            severity = str(row.get("severity") or "info")
            items.append(
                {
                    "id": f"alert-{row['id']}",
                    "evidence_type": "alert",
                    "evidence_type_name": "告警",
                    "title": row.get("alert_title"),
                    "summary": (
                        f"{severity} · {_STATUS_NAMES.get(status, status)} · "
                        f"当前值 {_number(row.get('current_value'))}"
                    ),
                    "evidence_level": "direct",
                    "evidence_level_name": "直接证据",
                    "occurred_at": row.get("last_fired_at"),
                    "target_id": str(row["id"]),
                    "status": status,
                    "severity": severity,
                    "resource_type": row.get("resource_type"),
                    "resource_code": row.get("resource_code"),
                }
            )
        return _result(items)

    async def query_metrics(
        *, window_start: datetime, window_end: datetime, scope_key: str
    ) -> dict[str, Any]:
        definitions = {
            str(item.get("metric_code")): item
            for item in await definition_db.list(DB.get())
            if item.get("status") == "active"
        }
        rows = await value_db.list(
            DB.get(),
            **_scope_filter(scope),
            scope_key=scope_key,
            window_end__gte=window_start,
        )
        items = []
        for row in rows:
            if row.get("window_start") is None or row["window_start"] >= window_end:
                continue
            code = str(row.get("metric_code") or "")
            definition = definitions.get(code) or {}
            assessment = str(row.get("assessment_status") or "unknown")
            data_status = str(row.get("data_status") or "unknown")
            items.append(
                {
                    "id": f"metric-{row['id']}",
                    "evidence_type": "metric",
                    "evidence_type_name": "指标",
                    "title": definition.get("metric_name") or code,
                    "summary": (
                        f"值 {_number(row.get('metric_value'))}{row.get('unit') or ''} · "
                        f"样本 {row.get('sample_count') or 0} · "
                        f"{_STATUS_NAMES.get(assessment, assessment)}"
                    ),
                    "evidence_level": "direct",
                    "evidence_level_name": "直接证据",
                    "occurred_at": row.get("window_end"),
                    "target_id": code,
                    "assessment_status": assessment,
                    "data_status": data_status,
                    "sample_count": int(row.get("sample_count") or 0),
                }
            )
        return _result(items)

    async def query_events(
        *, window_start: datetime, window_end: datetime, scope_key: str
    ) -> dict[str, Any]:
        del scope_key
        rows = await event_db.list(
            DB.get(),
            **_scope_filter(scope),
            occurred_at__gte=window_start,
        )
        items = []
        for row in rows:
            if not _in_window(row.get("occurred_at"), window_start, window_end):
                continue
            status = str(row.get("status") or "unknown")
            items.append(
                {
                    "id": f"event-{row['id']}",
                    "evidence_type": "event",
                    "evidence_type_name": "事件",
                    "title": row.get("event_type"),
                    "summary": (
                        f"{row.get('source_type')} · {_STATUS_NAMES.get(status, status)}"
                        + (f" · {row.get('stage')}" if row.get("stage") else "")
                    ),
                    "evidence_level": "associated",
                    "evidence_level_name": "关联证据",
                    "occurred_at": row.get("occurred_at"),
                    "target_id": str(row.get("event_id") or row["id"]),
                    "status": status,
                    "trace_id": row.get("trace_id"),
                    "error_category": row.get("error_category"),
                }
            )
        return _result(items)

    async def query_tasks(
        *, window_start: datetime, window_end: datetime, scope_key: str
    ) -> dict[str, Any]:
        del scope_key
        rows = await event_db.list(
            DB.get(),
            **_scope_filter(scope),
            occurred_at__gte=window_start,
        )
        items = []
        for row in rows:
            if not _in_window(row.get("occurred_at"), window_start, window_end):
                continue
            if row.get("task_id") is None and row.get("run_id") is None:
                continue
            status = str(row.get("status") or "unknown")
            target_id = row.get("task_id") or row.get("run_id")
            items.append(
                {
                    "id": f"task-event-{row['id']}",
                    "evidence_type": "task",
                    "evidence_type_name": "任务",
                    "title": row.get("event_type"),
                    "summary": (
                        f"任务 {target_id} · {_STATUS_NAMES.get(status, status)}"
                        + (f" · {row.get('stage')}" if row.get("stage") else "")
                    ),
                    "evidence_level": "associated",
                    "evidence_level_name": "关联证据",
                    "occurred_at": row.get("occurred_at"),
                    "target_id": str(target_id),
                    "status": status,
                    "trace_id": row.get("trace_id"),
                    "error_category": row.get("error_category"),
                }
            )
        return _result(items)

    registry.register("query_health_snapshots", query_health_snapshots)
    registry.register("query_alerts", query_alerts)
    registry.register("query_metrics", query_metrics)
    registry.register("query_events", query_events)
    registry.register("query_tasks", query_tasks)
    return registry


__all__ = ("build_monitoring_tool_registry",)
