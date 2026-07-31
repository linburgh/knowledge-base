from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.common import utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.common.log import LOG
from app.core.monitoring.resources import (
    runtime_resource_name,
    runtime_resource_sort_key,
)
from app.core.services import audit as audit_service
from app.db import audit_log as audit_log_db
from app.db import (
    monitor_alert as alert_db,
)
from app.db import (
    monitor_event as event_db,
)
from app.db import monitor_gather_target as gather_target_db
from app.db import (
    monitor_metric_rule as rule_db,
)
from app.db import (
    monitor_metric_value as value_db,
)
from app.db import (
    monitor_notification_channel as channel_db,
)
from app.db import (
    monitor_notification_policy as policy_db,
)
from app.db import (
    monitor_notification_policy_channel as policy_channel_db,
)
from app.db import (
    monitor_notification_record as notification_record_db,
)
from app.db import (
    monitor_state_snapshot as snapshot_db,
)
from app.db.api import check_db_connected
from app.db.base import DB
from app.schemas.monitoring import (
    MetricRuleRequest,
    MonitorEventRequest,
    MonitorSnapshotRequest,
    NotificationChannelRequest,
    NotificationPolicyRequest,
)

from .monitoring_access import require_monitoring_access, tenant_scope
from .monitoring_rule import evaluate_rule


def _scope_filter(scope: int | None) -> dict[str, Any]:
    return {} if scope is None else {"tenant_id": scope}


def _page(rows: list[dict[str, Any]], page: int, page_size: int) -> dict[str, Any]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise BusiException("分页参数无效")
    start = (page - 1) * page_size
    return {
        "items": rows[start : start + page_size],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
    }


def _bucket_5m(value: datetime) -> datetime:
    minute = value.minute - value.minute % 5
    return value.replace(minute=minute, second=0, microsecond=0)


def _runtime_bucket(value: datetime, interval_minutes: int) -> datetime:
    total_minutes = value.hour * 60 + value.minute
    bucket_minutes = total_minutes - total_minutes % interval_minutes
    return value.replace(
        hour=bucket_minutes // 60,
        minute=bucket_minutes % 60,
        second=0,
        microsecond=0,
    )


def _runtime_bucket_status(statuses: list[str]) -> str:
    if any(status in {"failed", "error", "stopped", "timeout"} for status in statuses):
        return "failed"
    if any(status in {"warning", "degraded", "stale"} for status in statuses):
        return "warning"
    if any(status in {"healthy", "normal", "idle", "busy"} for status in statuses):
        return "healthy"
    return "unknown"


def _overview_window(time_range: str) -> tuple[datetime, datetime]:
    durations = {
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }
    duration = durations.get(time_range)
    if duration is None:
        raise BusiException("time_range 必须是 15m、1h、6h、24h 或 7d")
    end_at = utils.utc_now()
    return end_at - duration, end_at


def _event_trend(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[datetime, dict[str, int]] = {}
    for event in events:
        occurred_at = event.get("occurred_at")
        if not isinstance(occurred_at, datetime):
            continue
        bucket = _bucket_5m(occurred_at)
        current = buckets.setdefault(bucket, {"total": 0, "abnormal": 0})
        current["total"] += 1
        if event.get("status") in {"failed", "error", "timeout"}:
            current["abnormal"] += 1
    return [{"window_end": bucket, **values} for bucket, values in sorted(buckets.items())]


def _alert_trend(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[datetime, dict[str, int]] = {}
    for alert in alerts:
        fired_at = alert.get("last_fired_at")
        if not isinstance(fired_at, datetime):
            continue
        bucket = _bucket_5m(fired_at)
        current = buckets.setdefault(
            bucket,
            {"firing": 0, "acknowledged": 0, "resolved": 0, "closed": 0},
        )
        status = str(alert.get("status") or "")
        if status in current:
            current[status] += 1
    return [{"window_end": bucket, **values} for bucket, values in sorted(buckets.items())]


def _resource_capacity(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resources = {
        "database-capacity": "数据库连接",
        "task-queue-capacity": "队列容量",
        "file-storage-capacity": "文件存储",
        "vector-storage-capacity": "向量存储",
    }
    result: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if snapshot.get("resource_type") != "capacity":
            continue
        resource_code = str(snapshot.get("resource_code") or "")
        resource_name = resources.get(resource_code)
        if resource_name is None:
            continue
        values = snapshot.get("status_value") or {}
        usage = values.get("usage")
        is_stale = (
            isinstance(snapshot.get("expires_at"), datetime)
            and snapshot["expires_at"] < utils.utc_now()
        )
        status = str(snapshot.get("status") or "")
        data_status = (
            "stale"
            if is_stale
            else "error"
            if status in {"failed", "error", "unavailable"}
            else "empty"
            if usage is None
            else "ready"
        )
        result.append(
            {
                "resource_code": resource_code,
                "resource_name": resource_name,
                "usage": float(usage) if usage is not None else None,
                "threshold": values.get("threshold"),
                "unit": values.get("unit") or "%",
                "used": values.get("used"),
                "capacity": values.get("capacity"),
                "data_status": data_status,
            }
        )
    order = {resource_code: index for index, resource_code in enumerate(resources)}
    return sorted(result, key=lambda item: order.get(str(item["resource_code"]), len(order)))


def _runtime_timeline(
    snapshots: list[dict[str, Any]],
    events: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
    time_range: str,
) -> list[dict[str, Any]]:
    """将真实探针事件按查询窗口投影为运行状态热力图。"""
    interval_minutes = {
        "15m": 5,
        "1h": 5,
        "6h": 30,
        "24h": 120,
        "7d": 720,
    }[time_range]
    end_bucket = _runtime_bucket(end_at, interval_minutes)
    duration_minutes = max(0, int((end_at - start_at).total_seconds() // 60))
    bucket_count = duration_minutes // interval_minutes + 1
    buckets = [
        end_bucket - timedelta(minutes=interval_minutes * index)
        for index in range(bucket_count - 1, -1, -1)
    ]

    result: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if snapshot.get("resource_type") == "capacity":
            continue
        resource_code = snapshot.get("resource_code")
        current_status = str(snapshot.get("status") or "unknown")
        if (
            isinstance(snapshot.get("expires_at"), datetime)
            and snapshot["expires_at"] < utils.utc_now()
        ):
            current_status = "stale"
        snapshot_time = snapshot.get("checked_at") or snapshot.get("updated_at")
        timeline: list[dict[str, str]] = []
        for bucket in buckets:
            matched = [
                event
                for event in events
                if event.get("source_code") == resource_code
                and isinstance(event.get("occurred_at"), datetime)
                and _runtime_bucket(event["occurred_at"], interval_minutes) == bucket
            ]
            statuses = [str(event.get("status") or "unknown") for event in matched]
            if (
                not statuses
                and isinstance(snapshot_time, datetime)
                and _runtime_bucket(snapshot_time, interval_minutes) == bucket
            ):
                statuses.append(current_status)
            timeline.append(
                {
                    "time": bucket.isoformat(),
                    "status": _runtime_bucket_status(statuses),
                }
            )
        result.append(
            {
                "resource_type": snapshot.get("resource_type"),
                "resource_code": resource_code,
                "resource_name": runtime_resource_name(
                    str(resource_code) if resource_code is not None else None
                ),
                "status": current_status,
                "checked_at": snapshot.get("updated_at") or snapshot.get("checked_at"),
                "data_status": "ready",
                "timeline": timeline,
            }
        )
    return sorted(result, key=runtime_resource_sort_key)[:5]


async def _overview_source(
    source: str,
    error_message: str,
    list_method: Any,
    db: Any,
    filters: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str | None]:
    try:
        rows = await list_method(db, **filters)
        return rows, "ready" if rows else "empty", None
    except Exception as exc:
        LOG.opt(exception=exc).error("自主监控总览数据源查询失败: {}", source)
        return [], "error", error_message


@check_db_connected
async def ingest_event(payload: MonitorEventRequest, current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    if scope is not None and payload.tenant_id not in {None, scope}:
        raise BusiException("不能写入其他租户数据", status_code=403)
    data = payload.model_dump()
    data["tenant_id"] = scope if scope is not None else payload.tenant_id
    db = DB.get()
    existing = await event_db.get(db, event_id=payload.event_id)
    if existing:
        return existing
    async with db.transaction():
        event_id = await event_db.insert_(db, **data)
        event = await event_db.get(db, id=event_id)
        await audit_service.record(
            db,
            action="monitor_event_ingested",
            target_type="monitor_event",
            target_id=event_id,
            summary={"event_type": payload.event_type, "source_code": payload.source_code},
        )
        return event


@check_db_connected
async def ingest_snapshot(
    payload: MonitorSnapshotRequest, current_user: CurrentUser
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    if scope is not None and payload.tenant_id not in {None, scope}:
        raise BusiException("不能写入其他租户数据", status_code=403)
    db = DB.get()
    filters = {
        "resource_type": payload.resource_type,
        "resource_code": payload.resource_code,
        "tenant_id": scope,
    }
    values = payload.model_dump()
    values["tenant_id"] = scope if scope is not None else payload.tenant_id
    values["updated_at"] = utils.utc_now()
    async with db.transaction():
        existing = await snapshot_db.get(db, **filters)
        if existing:
            await snapshot_db.update_(db, values, id=existing["id"])
            return await snapshot_db.get(db, id=existing["id"])
        row_id = await snapshot_db.insert_(db, **values)
        return await snapshot_db.get(db, id=row_id)


@check_db_connected
async def overview(
    current_user: CurrentUser,
    time_range: str = "1h",
    scope_key: str = "platform",
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    if scope_key not in {"platform", "tenant"}:
        raise BusiException("scope_key 必须是 platform 或 tenant")
    if scope_key == "tenant" and scope is None:
        if current_user.tenant_id is None:
            raise BusiException("当前未选择租户，不能查询租户范围")
        scope = int(current_user.tenant_id)
    start_at, end_at = _overview_window(time_range)
    db = DB.get()
    event_filters = {
        **_scope_filter(scope),
        "occurred_at__gte": start_at,
        "occurred_at__lte": end_at,
    }
    alert_filters = {
        **_scope_filter(scope),
        "last_fired_at__gte": start_at,
        "last_fired_at__lte": end_at,
    }
    snapshot_filters = {
        **_scope_filter(scope),
        "updated_at__gte": start_at,
        "updated_at__lte": end_at,
    }
    events, event_status, event_error = await _overview_source(
        "events",
        "事件数据查询失败",
        event_db.list,
        db,
        event_filters,
    )
    alerts, alert_status, alert_error = await _overview_source(
        "alerts",
        "告警数据查询失败",
        alert_db.list,
        db,
        alert_filters,
    )
    snapshots, snapshot_status, snapshot_error = await _overview_source(
        "snapshots",
        "运行快照查询失败",
        snapshot_db.list,
        db,
        snapshot_filters,
    )

    runtime_status = _runtime_timeline(
        snapshots,
        events,
        start_at,
        end_at,
        time_range,
    )

    business_status = [
        {
            "code": "qa",
            "name": "知识库问答",
            "status": "empty",
            "value": None,
            "value_label": "暂无问答数据",
            "metric_label": "--",
            "tip": (
                "表示当前授权范围内的问答链路是否正常，成功率反映请求完成情况，"
                "P95 表示较慢请求的响应耗时。"
            ),
        },
        {
            "code": "tasks",
            "name": "异步任务",
            "status": "empty",
            "value": None,
            "value_label": "暂无任务数据",
            "metric_label": "--",
            "tip": (
                "表示文档处理、索引构建和评测任务是否能够持续消费，"
                "最老等待时间用于判断任务是否长期积压。"
            ),
        },
        {
            "code": "evaluation",
            "name": "自主评测",
            "status": "empty",
            "value": None,
            "value_label": "暂无评测数据",
            "metric_label": "--",
            "tip": (
                "表示自主评测 Agent 当前是否运行，以及是否存在可追踪的评测运行，"
                "详细阶段和执行证据进入任务监控。"
            ),
        },
    ]
    for item in business_status:
        source_types = {
            "qa": {"qa", "question", "answer"},
            "tasks": {"task", "worker"},
            "evaluation": {"evaluation"},
        }[item["code"]]
        matched = [event for event in events if event.get("source_type") in source_types]
        if matched:
            has_error = any(event.get("status") in {"failed", "error"} for event in matched)
            if item["code"] == "tasks":
                waiting = [
                    event
                    for event in matched
                    if event.get("status") in {"queued", "pending", "started", "running"}
                ]
                item["status"] = "warning" if waiting or has_error else "normal"
                item["value_label"] = (
                    f"当前状态：积压 · 索引构建 {len(waiting)} 个"
                    if waiting
                    else "当前状态：正常 · 当前无积压"
                )
                oldest = min(
                    (
                        event.get("occurred_at")
                        for event in waiting
                        if isinstance(event.get("occurred_at"), datetime)
                    ),
                    default=None,
                )
                oldest_minutes = (
                    max(0, int((utils.utc_now() - oldest).total_seconds() // 60)) if oldest else 0
                )
                item["metric_label"] = f"最老 {oldest_minutes}分"
            elif item["code"] == "evaluation":
                running = [
                    event
                    for event in matched
                    if event.get("status") in {"started", "running", "queued"}
                ]
                item["status"] = "normal" if running and not has_error else "warning"
                item["value_label"] = (
                    "当前状态：运行中 · Agent 证据完整"
                    if running
                    else "当前状态：已停止 · 等待新的评测运行"
                )
                item["metric_label"] = f"运行 {len(running):02d}"
            else:
                successful = [
                    event
                    for event in matched
                    if event.get("status") in {"ok", "success", "completed", "ready"}
                ]
                success_rate = len(successful) / len(matched) * 100
                durations = sorted(
                    event.get("duration_ms")
                    for event in matched
                    if isinstance(event.get("duration_ms"), (int, float))
                )
                p95 = durations[max(0, int(len(durations) * 0.95) - 1)] if durations else 0
                item["status"] = "warning" if has_error else "normal"
                item["value_label"] = (
                    f"当前状态：{'异常' if has_error else '正常'} · 成功率 {success_rate:.1f}%"
                )
                item["metric_label"] = f"P95 {p95 / 1000:.1f}s"
            item["value"] = len(matched)

    recent_propagation_events = sorted(
        events,
        key=lambda row: row.get("occurred_at") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )[:100]
    propagation = [
        {
            "id": event.get("event_id"),
            "domain": event.get("source_type"),
            "title": event.get("event_type"),
            "status": event.get("status"),
            "occurred_at": event.get("occurred_at"),
            "trace_id": event.get("trace_id"),
        }
        for event in sorted(
            recent_propagation_events,
            key=lambda row: row.get("occurred_at") or datetime.min.replace(tzinfo=UTC),
        )
    ]
    unresolved_alerts = [
        alert for alert in alerts if alert.get("status") in {"firing", "acknowledged"}
    ][:100]
    alert_status_trend = _alert_trend(alerts)
    resource_capacity = _resource_capacity(snapshots)
    business_has_data = any(item["value"] is not None for item in business_status)

    section_statuses = {
        "unresolved_alerts": (
            "error" if alert_status == "error" else "ready" if unresolved_alerts else "empty"
        ),
        "runtime_status": (
            "error"
            if snapshot_status == "error"
            else "empty"
            if not runtime_status
            else "partial"
            if event_status == "error"
            else "ready"
        ),
        "business_status": (
            "error" if event_status == "error" else "ready" if business_has_data else "empty"
        ),
        "alert_status_trend": (
            "error" if alert_status == "error" else "ready" if alert_status_trend else "empty"
        ),
        "resource_capacity": (
            "error" if snapshot_status == "error" else "ready" if resource_capacity else "empty"
        ),
        "propagation": (
            "error" if event_status == "error" else "ready" if propagation else "empty"
        ),
    }
    section_errors = {
        key: value
        for key, value in {
            "unresolved_alerts": alert_error,
            "runtime_status": (
                snapshot_error
                if snapshot_status == "error"
                else "事件数据查询失败，当前仅展示运行快照"
                if event_status == "error" and runtime_status
                else None
            ),
            "business_status": event_error,
            "alert_status_trend": alert_error,
            "resource_capacity": snapshot_error,
            "propagation": event_error,
        }.items()
        if value
    }
    source_statuses = (event_status, alert_status, snapshot_status)
    if all(status == "error" for status in source_statuses):
        data_status = "error"
    elif any(status == "error" for status in source_statuses):
        data_status = "partial"
    elif events or alerts or snapshots:
        data_status = "ready"
    else:
        data_status = "empty"

    return {
        "core_metrics": {
            "request_count": len(events),
            "alert_count": sum(a.get("status") == "firing" for a in alerts),
        },
        "events": events[:100],
        "alerts": alerts[:100],
        "unresolved_alerts": unresolved_alerts,
        "runtime_status": runtime_status,
        "business_status": business_status,
        "alert_status_trend": alert_status_trend,
        "event_trend": _event_trend(events),
        "resource_capacity": resource_capacity,
        "propagation": propagation,
        "data_status": data_status,
        "section_statuses": section_statuses,
        "section_errors": section_errors,
        "scope_key": scope_key,
        "time_range": time_range,
        "window_start": start_at,
        "window_end": end_at,
        "business_updated_at": max(
            [row.get("occurred_at") for row in events if row.get("occurred_at")]
            or [None]
        ),
        "resource_capacity_updated_at": max(
            [
                row.get("checked_at") or row.get("updated_at")
                for row in snapshots
                if row.get("resource_type") == "capacity"
                and (row.get("checked_at") or row.get("updated_at"))
            ]
            or [None]
        ),
        "last_updated_at": max(
            [row.get("updated_at") for row in snapshots if row.get("updated_at")]
            + [row.get("last_fired_at") for row in alerts if row.get("last_fired_at")]
            or [None]
        ),
    }


_COLLECTION_STATUS_RANK = {"empty": 0, "ready": 1, "stale": 2, "partial": 3, "error": 4}
_COLLECTION_STATUS_NAME = {
    "ready": "正常",
    "partial": "部分失败",
    "error": "获取失败",
    "stale": "数据过期",
    "empty": "暂无数据",
}
_COLLECTION_TYPE_NAME = {
    "method": "通用采集",
    "api": "通用采集",
    "db": "通用采集",
    "worker": "周期采集",
    "collector": "周期采集",
    "probe": "依赖探针",
}


def _collection_domain(target: dict[str, Any]) -> tuple[str, str]:
    code = str(target.get("target_code") or "")
    if code.startswith("knowledge.") or code == "probe.qa":
        return "knowledge_qa", "问答链路"
    if code.startswith("document."):
        return "document_index", "文档索引"
    if code.startswith("evaluation."):
        return "evaluation", "评测执行"
    if code in {
        "probe.llm",
        "probe.embedding",
        "probe.rerank",
        "probe.vector",
        "probe.storage",
    }:
        return "external_dependency", "外部依赖"
    return "platform_runtime", "平台运行"


def _collection_event_status(event: dict[str, Any]) -> str:
    data_status = str(event.get("data_status") or "").lower()
    if data_status in {"stale", "expired"}:
        return "stale"
    if data_status in {"error", "failed", "unavailable"}:
        return "error"
    status = str(event.get("status") or "").lower()
    if status in {"healthy", "ok", "success", "completed", "ready", "resolved", "closed"}:
        return "ready"
    if status in {"warning", "degraded", "partial", "running", "started", "acknowledged"}:
        return "partial"
    if status in {"failed", "error", "timeout", "unavailable"}:
        return "error"
    return "empty"


def _collection_target_resource_codes(target: dict[str, Any]) -> set[str]:
    locator = target.get("target_locator") or {}
    return {
        str(target.get("target_code") or ""),
        str(locator.get("resource_code") or ""),
    } - {""}


def _collection_target_event(
    target: dict[str, Any],
    events: list[dict[str, Any]],
    at: datetime,
) -> dict[str, Any] | None:
    codes = _collection_target_resource_codes(target)
    return next(
        (
            event
            for event in events
            if event.get("occurred_at")
            and event["occurred_at"] <= at
            and str(event.get("source_code") or "") in codes
        ),
        None,
    )


def _collection_target_status(
    target: dict[str, Any],
    event: dict[str, Any] | None,
    at: datetime,
) -> str:
    if event is None:
        return "empty"
    locator = target.get("target_locator") or {}
    stale_after = locator.get("stale_after_seconds")
    if stale_after is None and locator.get("interval_seconds"):
        stale_after = int(locator["interval_seconds"]) * 3
    occurred_at = event.get("occurred_at")
    if stale_after and occurred_at and occurred_at + timedelta(seconds=int(stale_after)) < at:
        return "stale"
    return _collection_event_status(event)


def _collection_target_view(
    target: dict[str, Any],
    events: list[dict[str, Any]],
    at: datetime,
) -> dict[str, Any]:
    event = _collection_target_event(target, events, at)
    status = _collection_target_status(target, event, at)
    target_type = str(target.get("target_type") or "")
    locator = target.get("target_locator") or {}
    target_type_name = (
        "容量探针"
        if str(target.get("target_code") or "").startswith("capacity.")
        else _COLLECTION_TYPE_NAME.get(target_type, "周期采集")
    )
    return {
        **target,
        "target_type_name": target_type_name,
        "last_collected_at": event.get("occurred_at") if event else None,
        "duration_ms": event.get("duration_ms") if event else None,
        "data_status": status,
        "data_status_name": _COLLECTION_STATUS_NAME[status],
        "resource_code": locator.get("resource_code"),
    }


def _collection_timeline(
    targets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bucket = _bucket_5m(start_at)
    bucket_end = _bucket_5m(end_at)
    buckets: list[datetime] = []
    while bucket <= bucket_end:
        buckets.append(bucket)
        bucket += timedelta(minutes=5)
    trend: list[dict[str, Any]] = []
    heatmap: list[dict[str, Any]] = []
    domain_order: list[tuple[str, str]] = []
    for target in targets:
        domain = _collection_domain(target)
        if domain not in domain_order:
            domain_order.append(domain)
    for window_end in buckets:
        counts = {status: 0 for status in _COLLECTION_STATUS_RANK}
        domain_statuses: dict[str, list[str]] = {code: [] for code, _ in domain_order}
        observation_at = min(window_end + timedelta(minutes=5), end_at)
        for target in targets:
            event = _collection_target_event(target, events, observation_at)
            status = _collection_target_status(target, event, observation_at)
            counts[status] += 1
            domain_statuses[_collection_domain(target)[0]].append(status)
        trend.append({"window_end": window_end, **counts})
        for domain_code, domain_name in domain_order:
            statuses = domain_statuses[domain_code]
            status = (
                max(statuses, key=lambda item: _COLLECTION_STATUS_RANK[item])
                if statuses
                else "empty"
            )
            heatmap.append(
                {
                    "domain_code": domain_code,
                    "domain_name": domain_name,
                    "time": window_end,
                    "status": status,
                }
            )
    return trend, heatmap


@check_db_connected
async def collection_overview(
    current_user: CurrentUser,
    time_range: str = "1h",
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    if time_range != "1h":
        raise BusiException("采集总览当前仅支持最近1小时")
    scope = await tenant_scope(current_user)
    db = DB.get()
    now = utils.utc_now()
    events = await event_db.list(
        db,
        **_scope_filter(scope),
        occurred_at__gte=now - timedelta(hours=1),
    )
    targets = await gather_target_db.list(db, **_scope_filter(scope))
    views = [_collection_target_view(target, events, now) for target in targets]
    status_counts = {status: 0 for status in _COLLECTION_STATUS_RANK}
    for view in views:
        status_counts[str(view["data_status"])] += 1
    executed_count = sum(status_counts[status] for status in ("ready", "partial", "error", "stale"))
    success_count = status_counts["ready"]
    concern_count = status_counts["partial"] + status_counts["error"] + status_counts["stale"]
    trend, heatmap = _collection_timeline(targets, events, now - timedelta(hours=1), now)
    domains: list[dict[str, Any]] = []
    for domain_code, domain_name in dict(_collection_domain(target) for target in targets).items():
        domain_views = [
            view for view in views if _collection_domain(view)[0] == domain_code
        ]
        domain_status = (
            max(
                (str(view["data_status"]) for view in domain_views),
                key=lambda item: _COLLECTION_STATUS_RANK[item],
            )
            if domain_views
            else "empty"
        )
        last_collected_at = max(
            [
                view.get("last_collected_at")
                for view in domain_views
                if view.get("last_collected_at")
            ]
            or [None]
        )
        domains.append(
            {
                "domain_code": domain_code,
                "domain_name": domain_name,
                "status": domain_status,
                "status_name": _COLLECTION_STATUS_NAME[domain_status],
                "last_collected_at": last_collected_at,
                "target_count": len(domain_views),
                "impact": (
                    "有影响"
                    if domain_status == "error"
                    else "需关注"
                    if domain_status in {"partial", "stale"}
                    else "无影响"
                ),
            }
        )
    conclusion = "success" if concern_count == 0 and executed_count else "partial"
    return {
        "conclusion": conclusion if executed_count else "empty",
        "conclusion_text": (
            "当前暂无已执行的采集结果"
            if not executed_count
            else "采集链路整体正常"
            if conclusion == "success"
            else f"采集链路整体可用，{concern_count} 个目标需要关注"
        ),
        "success_rate": success_count / executed_count if executed_count else None,
        "status_distribution": status_counts,
        "target_count": len(targets),
        "normal_count": success_count,
        "concern_count": concern_count,
        "stale_count": status_counts["stale"],
        "trend": trend,
        "heatmap": heatmap,
        "domains": domains,
        "last_updated_at": max(
            [view.get("last_collected_at") for view in views if view.get("last_collected_at")]
            or [None]
        ),
        "data_status": "ready" if executed_count else "empty",
    }


@check_db_connected
async def target_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    target_name: str | None = None,
    target_type: str | None = None,
    data_status: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    db = DB.get()
    scope_filter = _scope_filter(await tenant_scope(current_user))
    targets = await gather_target_db.list(db, **scope_filter)
    now = utils.utc_now()
    events = await event_db.list(
        db,
        **scope_filter,
        occurred_at__gte=now - timedelta(hours=1),
    )
    rows = [_collection_target_view(target, events, now) for target in targets]
    if target_name:
        rows = [
            row for row in rows if target_name.lower() in str(row.get("target_name", "")).lower()
        ]
    if target_type:
        rows = [
            row
            for row in rows
            if row.get("target_type") == target_type or row.get("target_type_name") == target_type
        ]
    if data_status:
        rows = [row for row in rows if row.get("data_status") == data_status]
    return _page(rows, page, page_size)


@check_db_connected
async def metrics_overview(current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    rows = await value_db.list(DB.get(), **_scope_filter(await tenant_scope(current_user)))
    return {
        "items": rows,
        "trend": _event_trend(
            await event_db.list(DB.get(), **_scope_filter(await tenant_scope(current_user)))
        ),
        "data_status": "ready" if rows else "empty",
    }


@check_db_connected
async def metric_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    metric_name: str | None = None,
    scope_key: str | None = None,
    data_status: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    rows = await value_db.list(DB.get(), **_scope_filter(await tenant_scope(current_user)))
    if metric_name:
        keyword = metric_name.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("metric_code") or "").lower()]
    if scope_key:
        rows = [row for row in rows if row.get("scope_key") == scope_key]
    if data_status:
        rows = [row for row in rows if row.get("data_status") == data_status]
    return _page(rows, page, page_size)


@check_db_connected
async def tasks_overview(current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    events = await event_db.list(DB.get(), **_scope_filter(await tenant_scope(current_user)))
    task_events = [
        event for event in events if event.get("source_type") in {"task", "evaluation", "worker"}
    ]
    statuses: dict[str, int] = {}
    for event in task_events:
        status = str(event.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "status_distribution": statuses,
        "items": task_events,
        "trend": _event_trend(task_events),
        "data_status": "ready" if task_events else "empty",
    }


@check_db_connected
async def task_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    task_name: str | None = None,
    task_type: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    events = await event_db.list(DB.get(), **_scope_filter(await tenant_scope(current_user)))
    rows = [
        event
        for event in events
        if event.get("source_type") in {"task", "evaluation", "worker"}
    ]
    if task_name:
        keyword = task_name.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("source_code") or "").lower()]
    if task_type:
        rows = [row for row in rows if row.get("source_type") == task_type]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    return _page(rows, page, page_size)


@check_db_connected
async def notification_record_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    status: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    filters = _scope_filter(await tenant_scope(current_user))
    if status:
        filters["status"] = status
    return _page(await notification_record_db.list(DB.get(), **filters), page, page_size)


@check_db_connected
async def audit_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    actor_id: str | None = None,
    action: str | None = None,
    result: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    rows = await audit_log_db.list(DB.get())
    if actor_id:
        keyword = actor_id.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("actor_id") or "").lower()]
    if action:
        rows = [row for row in rows if row.get("action") == action]
    if result:
        rows = [row for row in rows if row.get("result") == result]
    if target_id:
        keyword = target_id.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("target_id") or "").lower()]
    return _page(rows, page, page_size)


@check_db_connected
async def analysis_overview(current_user: CurrentUser) -> dict[str, Any]:
    result = await overview(current_user)
    return {
        "conclusion": "需要关注" if result["alerts"] else "当前稳定",
        "alerts": result["alerts"],
        "evidence": result["events"][:50],
        "timeline": result["events"][:50],
        "suggestions": ["优先查看未恢复告警关联的指标和事件。"] if result["alerts"] else [],
    }


@check_db_connected
async def event_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    event_type: str | None = None,
    source_code: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    filters = _scope_filter(await tenant_scope(current_user))
    if event_type:
        filters["event_type"] = event_type
    rows = await event_db.list(DB.get(), **filters)
    if source_code:
        keyword = source_code.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("source_code") or "").lower()]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    return _page(rows, page, page_size)


@check_db_connected
async def alert_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    status: str | None = None,
    severity: str | None = None,
    resource_code: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    filters = _scope_filter(await tenant_scope(current_user))
    if status:
        filters["status"] = status
    if severity:
        filters["severity"] = severity
    rows = await alert_db.list(DB.get(), **filters)
    if resource_code:
        keyword = resource_code.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("resource_code") or "").lower()]
    return _page(rows, page, page_size)


@check_db_connected
async def metric_series(
    current_user: CurrentUser, metric_code: str, scope_key: str, limit: int = 60
) -> list[dict[str, Any]]:
    await require_monitoring_access(current_user)
    filters = {
        **_scope_filter(await tenant_scope(current_user)),
        "metric_code": metric_code,
        "scope_key": scope_key,
    }
    return (await value_db.list(DB.get(), **filters))[-min(limit, 200) :]


@check_db_connected
async def create_rule(payload: MetricRuleRequest, current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    db = DB.get()
    async with db.transaction():
        rule_id = await rule_db.insert_(
            db,
            **payload.model_dump(),
            effective_at=utils.utc_now(),
            created_by=current_user.user_id,
        )
        return await rule_db.get(db, id=rule_id)


@check_db_connected
async def list_rules(current_user: CurrentUser) -> list[dict[str, Any]]:
    await require_monitoring_access(current_user)
    return await rule_db.list(DB.get(), enabled=True)


@check_db_connected
async def apply_rule(rule: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any] | None:
    decision = evaluate_rule(rule, metric.get("metric_value"), int(metric.get("sample_count") or 0))
    if decision.action == "ignore":
        return None
    db = DB.get()
    alert_key = f"{rule['id']}:{metric.get('scope_key')}"
    existing = await alert_db.get(db, alert_key=alert_key)
    now = metric.get("window_end") or datetime.now(UTC)
    async with db.transaction():
        if decision.action == "recover":
            if existing and existing.get("status") in {"firing", "acknowledged"}:
                await alert_db.update_(
                    db,
                    {"status": "resolved", "resolved_at": now, "updated_at": now},
                    id=existing["id"],
                )
                recovered = await alert_db.get(db, id=existing["id"])
                await _enqueue_notifications(db, recovered, "recovery")
                await audit_service.record(
                    db,
                    action="monitor_alert_recovered",
                    target_type="monitor_alert",
                    target_id=existing["id"],
                    summary={"metric_code": rule["metric_code"], "reason": decision.reason},
                )
                return recovered
            return existing
        values = {
            "alert_key": alert_key,
            "rule_id": rule["id"],
            "metric_code": rule["metric_code"],
            "alert_title": f"指标异常：{rule['metric_code']}",
            "severity": decision.severity,
            "status": "firing",
            "tenant_id": metric.get("tenant_id"),
            "kb_id": metric.get("kb_id"),
            "resource_code": metric.get("scope_key"),
            "current_value": metric.get("metric_value"),
            "threshold": decision.threshold,
            "sample_count": metric.get("sample_count"),
            "first_fired_at": existing.get("first_fired_at", now) if existing else now,
            "last_fired_at": now,
            "firing_count": (existing.get("firing_count", 0) + 1) if existing else 1,
            "updated_at": now,
        }
        if existing:
            await alert_db.update_(db, values, id=existing["id"])
            alert = await alert_db.get(db, id=existing["id"])
            await _enqueue_notifications(db, alert, "firing")
            return alert
        alert_id = await alert_db.insert_(db, **values)
        alert = await alert_db.get(db, id=alert_id)
        await _enqueue_notifications(db, alert, "firing")
        await audit_service.record(
            db,
            action="monitor_alert_fired",
            target_type="monitor_alert",
            target_id=alert_id,
            summary={"metric_code": rule["metric_code"], "severity": decision.severity},
        )
        return alert


async def _enqueue_notifications(db, alert: dict[str, Any], event_type: str) -> None:
    if not alert:
        return
    policies = await policy_db.list(db, status="enabled")
    now = utils.utc_now()
    for policy in policies:
        if policy.get("severity") and policy["severity"] != alert.get("severity"):
            continue
        event_types = policy.get("event_types") or []
        if event_types and event_type not in event_types:
            continue
        links = await policy_channel_db.list(db, policy_id=policy["id"])
        for link in links:
            channel = await channel_db.get(db, id=link["channel_id"])
            if not channel or channel.get("status") != "enabled":
                continue
            recent = await notification_record_db.get(
                db,
                alert_id=alert["id"],
                policy_id=policy["id"],
                channel_id=channel["id"],
                event_type=event_type,
            )
            if recent:
                continue
            await notification_record_db.insert_(
                db,
                alert_id=alert["id"],
                policy_id=policy["id"],
                channel_id=channel["id"],
                event_type=event_type,
                receiver_scope=channel.get("receiver_scope") or {},
                status="pending",
                retry_count=0,
                created_at=now,
            )
    await audit_service.record(
        db,
        action="monitor_notification_enqueued",
        target_type="monitor_alert",
        target_id=alert["id"],
        summary={"event_type": event_type},
    )


@check_db_connected
async def alert_action(alert_id: int, action: str, current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    filters = {"id": alert_id, **_scope_filter(await tenant_scope(current_user))}
    alert = await alert_db.get(DB.get(), **filters)
    if not alert:
        raise BusiException("告警不存在", status_code=404)
    now = utils.utc_now()
    values = {"updated_at": now}
    if action == "acknowledge":
        values.update(
            status="acknowledged", acknowledged_by=current_user.user_id, acknowledged_at=now
        )
    elif action == "resolve":
        values.update(status="resolved", resolved_at=now)
    else:
        raise BusiException("不支持的告警操作")
    async with DB.get().transaction():
        await alert_db.update_(DB.get(), values, id=alert_id)
        updated = await alert_db.get(DB.get(), id=alert_id)
        await audit_service.record(
            DB.get(),
            action=f"monitor_alert_{action}",
            target_type="monitor_alert",
            target_id=alert_id,
            summary={"status": updated.get("status")},
        )
        return updated


async def _list_config(current_user: CurrentUser, db_module, **filters):
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    if scope is not None:
        filters["tenant_id"] = scope
    return await db_module.list(DB.get(), **filters)


async def _config_page(
    current_user: CurrentUser,
    db_module,
    page: int,
    page_size: int,
    name_field: str,
    keyword: str | None = None,
    **filters,
) -> dict[str, Any]:
    rows = await _list_config(current_user, db_module, **filters)
    if keyword:
        normalized = keyword.strip().lower()
        rows = [
            row
            for row in rows
            if normalized in str(row.get(name_field) or "").lower()
        ]
    return _page(rows, page, page_size)


@check_db_connected
async def rule_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    metric_name: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    filters = {} if enabled is None else {"enabled": enabled}
    return await _config_page(
        current_user,
        rule_db,
        page,
        page_size,
        "metric_code",
        metric_name,
        **filters,
    )


@check_db_connected
async def list_channels(current_user: CurrentUser):
    return await _list_config(current_user, channel_db)


@check_db_connected
async def channel_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    channel_name: str | None = None,
) -> dict[str, Any]:
    return await _config_page(
        current_user,
        channel_db,
        page,
        page_size,
        "channel_name",
        channel_name,
    )


@check_db_connected
async def create_channel(payload: NotificationChannelRequest, current_user: CurrentUser):
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    data = {
        **payload.model_dump(),
        "tenant_id": scope,
        "effective_at": utils.utc_now(),
        "created_by": current_user.user_id,
    }
    async with DB.get().transaction():
        row_id = await channel_db.insert_(DB.get(), **data)
        return await channel_db.list(DB.get(), id=row_id)


@check_db_connected
async def list_policies(current_user: CurrentUser):
    return await _list_config(current_user, policy_db)


@check_db_connected
async def policy_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    policy_name: str | None = None,
) -> dict[str, Any]:
    return await _config_page(
        current_user,
        policy_db,
        page,
        page_size,
        "policy_name",
        policy_name,
    )


@check_db_connected
async def create_policy(payload: NotificationPolicyRequest, current_user: CurrentUser):
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    db = DB.get()
    async with db.transaction():
        policy_id = await policy_db.insert_(
            db,
            **payload.model_dump(exclude={"channel_ids"}),
            tenant_id=scope,
            created_by=current_user.user_id,
        )
        for channel_id in payload.channel_ids:
            await policy_channel_db.insert_(db, policy_id=policy_id, channel_id=channel_id)
        rows = await policy_db.list(db, id=policy_id)
        return rows[0] if rows else None


__all__ = (
    "ingest_event",
    "ingest_snapshot",
    "overview",
    "collection_overview",
    "target_page",
    "metrics_overview",
    "metric_page",
    "tasks_overview",
    "task_page",
    "event_page",
    "alert_page",
    "metric_series",
    "create_rule",
    "list_rules",
    "rule_page",
    "apply_rule",
    "alert_action",
    "channel_page",
    "policy_page",
    "list_channels",
    "create_channel",
    "list_policies",
    "create_policy",
    "notification_record_page",
    "audit_page",
    "analysis_overview",
)
