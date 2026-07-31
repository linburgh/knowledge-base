from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.common import utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
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
    return [
        {"window_end": bucket, **values}
        for bucket, values in sorted(buckets.items())
    ]


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
    return [
        {"window_end": bucket, **values}
        for bucket, values in sorted(buckets.items())
    ]


def _resource_capacity(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for snapshot in snapshots:
        values = snapshot.get("status_value") or {}
        usage = values.get("usage")
        if usage is None:
            continue
        result.append(
            {
                "resource_code": snapshot.get("resource_code"),
                "resource_name": values.get("name") or snapshot.get("resource_code"),
                "usage": float(usage),
                "threshold": values.get("threshold"),
                "unit": values.get("unit") or "%",
                "data_status": "ready",
            }
        )
    return result


def _runtime_timeline(
    snapshots: list[dict[str, Any]], events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """将当前快照和事件异常投影为总览使用的 5 分钟状态热力图。"""
    timestamps = [
        value
        for row in snapshots + events
        for value in [row.get("updated_at") or row.get("occurred_at")]
        if isinstance(value, datetime)
    ]
    end = _bucket_5m(max(timestamps, default=utils.utc_now()))
    buckets = [end - timedelta(minutes=5 * index) for index in range(12, -1, -1)]

    result: list[dict[str, Any]] = []
    for snapshot in snapshots:
        resource_code = snapshot.get("resource_code")
        current_status = str(snapshot.get("status") or "unknown")
        timeline: list[dict[str, str]] = []
        for bucket in buckets:
            matched = [
                event
                for event in events
                if event.get("source_code") == resource_code
                and isinstance(event.get("occurred_at"), datetime)
                and _bucket_5m(event["occurred_at"]) == bucket
            ]
            status = current_status
            if any(event.get("status") in {"failed", "error", "timeout"} for event in matched):
                status = "failed"
            elif any(event.get("status") in {"warning", "degraded"} for event in matched):
                status = "warning"
            timeline.append({"time": bucket.strftime("%H:%M"), "status": status})
        result.append(
            {
                "resource_type": snapshot.get("resource_type"),
                "resource_code": resource_code,
                "status": current_status,
                "checked_at": snapshot.get("updated_at") or snapshot.get("checked_at"),
                "data_status": "ready",
                "timeline": timeline,
            }
        )
    return result


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
async def overview(current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    db = DB.get()
    event_filters = _scope_filter(scope)
    alert_filters = _scope_filter(scope)
    events = await event_db.list(db, **event_filters)
    alerts = await alert_db.list(db, **alert_filters)
    snapshots = await snapshot_db.list(db, **event_filters)

    runtime_status = _runtime_timeline(snapshots, events)

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
                    max(0, int((utils.utc_now() - oldest).total_seconds() // 60))
                    if oldest
                    else 0
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
    return {
        "core_metrics": {
            "request_count": len(events),
            "alert_count": sum(a.get("status") == "firing" for a in alerts),
        },
        "events": events[:100],
        "alerts": alerts[:100],
        "unresolved_alerts": [
            alert for alert in alerts if alert.get("status") in {"firing", "acknowledged"}
        ][:100],
        "runtime_status": runtime_status,
        "business_status": business_status,
        "alert_status_trend": _alert_trend(alerts),
        "event_trend": _event_trend(events),
        "resource_capacity": _resource_capacity(snapshots),
        "propagation": propagation,
        "data_status": "ready" if events or alerts or snapshots else "empty",
        "last_updated_at": max(
            [row.get("updated_at") for row in snapshots if row.get("updated_at")]
            + [row.get("last_fired_at") for row in alerts if row.get("last_fired_at")]
            or [None]
        ),
    }


@check_db_connected
async def collection_overview(current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    db = DB.get()
    events = await event_db.list(db, **_scope_filter(scope))
    targets = await gather_target_db.list(db, **_scope_filter(scope))
    status_counts: dict[str, int] = {}
    for event in events:
        status = str(event.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    success_count = sum(
        value
        for key, value in status_counts.items()
        if key in {"ok", "success", "completed", "ready"}
    )
    heatmap = [
        {"time": point["window_end"], "count": point["total"], "status": "ready"}
        for point in _event_trend(events)
    ]
    return {
        "conclusion": "success" if not events or success_count == len(events) else "partial",
        "success_rate": success_count / len(events) if events else None,
        "status_distribution": status_counts,
        "target_count": len(targets),
        "heatmap": heatmap,
        "data_status": "ready" if events else "empty",
    }


@check_db_connected
async def target_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    target_name: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    rows = await gather_target_db.list(DB.get(), **_scope_filter(await tenant_scope(current_user)))
    if target_name:
        rows = [
            row for row in rows if target_name.lower() in str(row.get("target_name", "")).lower()
        ]
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
async def audit_page(current_user: CurrentUser, page: int, page_size: int) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    return _page(await audit_log_db.list(DB.get()), page, page_size)


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
    current_user: CurrentUser, page: int, page_size: int, event_type: str | None = None
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    filters = _scope_filter(await tenant_scope(current_user))
    if event_type:
        filters["event_type"] = event_type
    return _page(await event_db.list(DB.get(), **filters), page, page_size)


@check_db_connected
async def alert_page(
    current_user: CurrentUser, page: int, page_size: int, status: str | None = None
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    filters = _scope_filter(await tenant_scope(current_user))
    if status:
        filters["status"] = status
    return _page(await alert_db.list(DB.get(), **filters), page, page_size)


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


@check_db_connected
async def list_channels(current_user: CurrentUser):
    return await _list_config(current_user, channel_db)


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
    "tasks_overview",
    "event_page",
    "alert_page",
    "metric_series",
    "create_rule",
    "list_rules",
    "apply_rule",
    "alert_action",
    "list_channels",
    "create_channel",
    "list_policies",
    "create_policy",
    "notification_record_page",
    "audit_page",
    "analysis_overview",
)
