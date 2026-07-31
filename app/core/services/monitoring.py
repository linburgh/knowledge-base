from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.agents.monitoring import MonitoringAgent
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
from app.db import evaluation_run as evaluation_run_db
from app.db import evaluation_task as evaluation_task_db
from app.db import indexing_task as indexing_task_db
from app.db import knowledge_base as knowledge_base_db
from app.db import (
    monitor_alert as alert_db,
)
from app.db import monitor_alert_evidence as alert_evidence_db
from app.db import (
    monitor_event as event_db,
)
from app.db import monitor_gather_target as gather_target_db
from app.db import monitor_metric_definition as definition_db
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
from app.db import user as user_db
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


_EVENT_SOURCE_NAMES = {
    "task": "任务运行",
    "worker": "Worker",
    "alert": "告警",
    "collection": "采集与依赖",
}
_EVENT_SOURCE_COLORS = {
    "task": "#5695f4",
    "worker": "#72c99b",
    "alert": "#e5b347",
    "collection": "#aeb9c8",
}
_EVENT_DOMAIN_NAMES = {
    "qa": "知识库问答",
    "platform": "平台运行",
    "task": "异步任务",
    "evaluation": "自主评测",
}
_EVENT_STATUS_NAMES = {
    "completed": "已完成",
    "success": "已完成",
    "succeeded": "已完成",
    "healthy": "正常",
    "normal": "正常",
    "started": "触发中",
    "running": "运行中",
    "processing": "运行中",
    "retrying": "重试中",
    "idle": "空闲",
    "busy": "忙碌",
    "warning": "需关注",
    "degraded": "部分降级",
    "failed": "失败",
    "error": "异常",
    "timeout": "已超时",
    "stale": "已过期",
    "stopped": "已停止",
    "cancelled": "已取消",
    "firing": "触发中",
    "resolved": "已恢复",
}
_EVENT_RESOURCE_NAMES = {
    "api.http": "接口服务",
    "db.execute": "数据库访问",
    "evaluation": "自主评测 Worker",
    "evaluation.run": "自主评测运行",
    "indexing": "索引构建 Worker",
    "document.indexing": "文档索引",
    "document.ingestion": "文档处理",
    "knowledge.qa": "知识库问答",
    "worker-runtime": "工作节点",
}

_ALERT_SEVERITY_NAMES = {
    "critical": "严重",
    "warning": "警告",
    "info": "提示",
}
_ALERT_SEVERITY_COLORS = {
    "critical": "#dd6673",
    "warning": "#e5b347",
    "info": "#5695f4",
}
_ALERT_STATUS_NAMES = {
    "firing": "触发中",
    "acknowledged": "已确认",
    "suppressed": "已抑制",
    "resolved": "已恢复",
    "closed": "已关闭",
}
_NOTIFICATION_STATUS_NAMES = {
    "pending": "待发送",
    "retrying": "重试中",
    "sent": "已完成",
    "success": "已完成",
    "completed": "已完成",
    "failed": "失败",
}


def _event_source_category(event: dict[str, Any]) -> str:
    source_type = str(event.get("source_type") or "")
    event_type = str(event.get("event_type") or "")
    if source_type == "alert" or "alert" in event_type:
        return "alert"
    if source_type == "worker" or event_type.startswith("worker_"):
        return "worker"
    if source_type in {"document_index", "evaluation_agent", "task"}:
        return "task"
    return "collection"


def _event_domain(event: dict[str, Any]) -> str:
    source_type = str(event.get("source_type") or "")
    if source_type == "knowledge_agent":
        return "qa"
    if source_type == "evaluation_agent":
        return "evaluation"
    if source_type in {"document_index", "task", "worker"}:
        return "task"
    return "platform"


def _event_type_code(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    source_category = _event_source_category(event)
    if source_category == "alert":
        recovered = "recover" in event_type or "resolve" in event_type
        return "alert_recovery" if recovered else "alert_trigger"
    if source_category == "worker":
        return "worker_status"
    if event_type.startswith("evaluation_") and event_type not in {
        "evaluation_run_completed",
        "evaluation_run_failed",
        "evaluation_run_timeout",
        "evaluation_run_cancelled",
    }:
        return "evaluation_stage"
    if source_category == "task":
        return "task_status"
    if "probe" in event_type or source_category == "collection":
        return "collection_status"
    return "service_status"


_EVENT_TYPE_NAMES = {
    "service_status": "服务状态",
    "worker_status": "Worker 状态",
    "task_status": "任务状态",
    "evaluation_stage": "评测阶段",
    "collection_status": "采集状态",
    "alert_trigger": "告警触发",
    "alert_recovery": "告警恢复",
}


def _event_resource_name(event: dict[str, Any]) -> str:
    source_code = str(event.get("source_code") or "")
    if source_code in _EVENT_RESOURCE_NAMES:
        return _EVENT_RESOURCE_NAMES[source_code]
    known_runtime_name = runtime_resource_name(source_code)
    return source_code if known_runtime_name == "其他服务" else known_runtime_name


_EVENT_SENSITIVE_FIELDS = {
    "answer",
    "api_key",
    "authorization",
    "content",
    "document",
    "password",
    "prompt",
    "question",
    "secret",
    "snippet",
    "token",
}


def _sanitize_event_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_event_context(item)
            for key, item in value.items()
            if not any(field in str(key).lower() for field in _EVENT_SENSITIVE_FIELDS)
        }
    if isinstance(value, list):
        return [_sanitize_event_context(item) for item in value[:50]]
    return value


def _event_view(event: dict[str, Any], *, include_context: bool = False) -> dict[str, Any]:
    row = dict(event)
    event_type_code = _event_type_code(event)
    status = str(event.get("status") or "unknown")
    status_name = _EVENT_STATUS_NAMES.get(status, "未知状态")
    resource_name = _event_resource_name(event)
    row.update(
        event_type_code=event_type_code,
        event_type_name=_EVENT_TYPE_NAMES[event_type_code],
        event_content=f"{resource_name}：{status_name}",
        monitor_domain=_event_domain(event),
        monitor_domain_name=_EVENT_DOMAIN_NAMES[_event_domain(event)],
        source_category=_event_source_category(event),
        source_category_name=_EVENT_SOURCE_NAMES[_event_source_category(event)],
        resource_name=resource_name,
        status_name=status_name,
        association_id=(
            event.get("trace_id")
            or event.get("task_id")
            or event.get("run_id")
            or event.get("request_id")
        ),
    )
    if include_context:
        row["payload"] = _sanitize_event_context(row.get("payload") or {})
    else:
        row.pop("payload", None)
    return row


def _visible_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event_type") != "worker_idle"]


def _monitor_domain(metric_code: str, definitions: dict[str, dict[str, Any]]) -> tuple[str, str]:
    definition = definitions.get(metric_code) or {}
    domain = str(definition.get("metric_domain") or "platform")
    return domain, _METRIC_DOMAIN_NAMES.get(domain, "平台运行")


def _alert_view(alert: dict[str, Any], definitions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = dict(alert)
    metric_code = str(alert.get("metric_code") or "")
    domain, domain_name = _monitor_domain(metric_code, definitions)
    resource_code = str(alert.get("resource_code") or metric_code)
    started_at = alert.get("first_fired_at")
    ended_at = alert.get("resolved_at") or alert.get("closed_at") or utils.utc_now()
    duration_seconds = None
    if isinstance(started_at, datetime) and isinstance(ended_at, datetime):
        duration_seconds = max(0, int((ended_at - started_at).total_seconds()))
    row.update(
        severity_name=_ALERT_SEVERITY_NAMES.get(str(alert.get("severity")), "未知级别"),
        status_name=_ALERT_STATUS_NAMES.get(str(alert.get("status")), "未知状态"),
        monitor_domain=domain,
        monitor_domain_name=domain_name,
        resource_name=_event_resource_name({"source_code": resource_code}),
        duration_seconds=duration_seconds,
        acknowledged_by_name=alert.get("acknowledged_by") or "—",
    )
    return row


def _seconds_label(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400} 天"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} 小时"
    return f"{max(1, seconds // 60)} 分钟"


def _rule_view(rule: dict[str, Any], definitions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = dict(rule)
    metric_code = str(rule.get("metric_code") or "")
    definition = definitions.get(metric_code) or {}
    domain, domain_name = _monitor_domain(metric_code, definitions)
    critical_threshold = rule.get("critical_threshold")
    warning_threshold = rule.get("warning_threshold")
    severity = "critical" if critical_threshold is not None else "warning"
    threshold = critical_threshold if critical_threshold is not None else warning_threshold
    operator = str(definition.get("threshold_operator") or ">")
    trigger_expression = (
        f"{metric_code} {operator} {threshold}" if threshold is not None else metric_code
    )
    consecutive_periods = int(rule.get("consecutive_periods") or 1)
    recovery_periods = int(rule.get("recovery_periods") or 1)
    recovery_threshold = rule.get("recovery_threshold")
    recovery_condition = (
        f"连续 {recovery_periods} 个周期恢复至 {recovery_threshold}"
        if recovery_threshold is not None
        else f"连续 {recovery_periods} 个周期恢复"
    )
    row.update(
        rule_name=f"{definition.get('metric_name') or metric_code}告警",
        monitor_domain=domain,
        monitor_domain_name=domain_name,
        severity=severity,
        severity_name=_ALERT_SEVERITY_NAMES[severity],
        trigger_expression=trigger_expression,
        trigger_window=(
            "单次计算" if consecutive_periods == 1 else f"连续 {consecutive_periods} 个周期"
        ),
        recovery_condition=recovery_condition,
        status="enabled" if rule.get("enabled") else "disabled",
        status_name="启用" if rule.get("enabled") else "停用",
        window_label=_seconds_label(int(rule.get("window_seconds") or 300)),
    )
    return row


def _latest_rule_versions(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for rule in rules:
        key = (str(rule.get("metric_code") or ""), str(rule.get("scope_type") or ""))
        if key not in latest or int(rule.get("version") or 0) > int(
            latest[key].get("version") or 0
        ):
            latest[key] = rule
    return sorted(
        latest.values(),
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        reverse=True,
    )


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


def _alert_overview_trend(
    alerts: list[dict[str, Any]], start_at: datetime, end_at: datetime
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    cursor = _bucket_5m(start_at)
    final_bucket = _bucket_5m(end_at)
    while cursor <= final_bucket:
        bucket_end = cursor + timedelta(minutes=5)
        newly_fired = sum(
            1
            for alert in alerts
            if isinstance(alert.get("first_fired_at"), datetime)
            and cursor <= alert["first_fired_at"] < bucket_end
        )
        recovered = sum(
            1
            for alert in alerts
            if isinstance(alert.get("resolved_at"), datetime)
            and cursor <= alert["resolved_at"] < bucket_end
        )
        unresolved = sum(
            1
            for alert in alerts
            if isinstance(alert.get("first_fired_at"), datetime)
            and alert["first_fired_at"] < bucket_end
            and not (
                isinstance(alert.get("resolved_at"), datetime) and alert["resolved_at"] < bucket_end
            )
            and not (
                isinstance(alert.get("closed_at"), datetime) and alert["closed_at"] < bucket_end
            )
        )
        points.append(
            {
                "window_end": min(bucket_end, end_at),
                "newly_fired": newly_fired,
                "unresolved": unresolved,
                "recovered": recovered,
            }
        )
        cursor = bucket_end
    return points


def _metric_status(metric: dict[str, Any]) -> str:
    if metric.get("data_status") != "ready":
        return "unknown"
    assessment = str(metric.get("assessment_status") or "ready")
    if assessment in {"unknown", "unavailable", "indeterminate"}:
        return "unknown"
    if assessment in {"failed", "error", "critical", "noncompliant"}:
        return "failed"
    if assessment in {"warning", "partial", "degraded"}:
        return "warning"
    return "ready"


_METRIC_DOMAIN_NAMES = {
    "qa": "知识库问答",
    "platform": "平台运行",
    "resource": "平台运行",
    "task": "异步任务",
    "evaluation": "自主评测",
}
_METRIC_DOMAIN_ORDER = {"qa": 0, "platform": 1, "resource": 1, "task": 2, "evaluation": 3}
_METRIC_STATUS_NAMES = {
    "ready": "达标",
    "warning": "预警",
    "failed": "不达标",
    "unknown": "无法判定",
}
_METRIC_DATA_STATUS_NAMES = {
    "ready": "已完成",
    "partial": "部分数据",
    "empty": "暂无数据",
    "stale": "数据过期",
    "error": "获取失败",
}
_METRIC_UNIT_NAMES = {
    "count": "项",
    "percent": "%",
    "ratio": "%",
    "ms": "毫秒",
    "seconds": "秒",
    "bytes": "字节",
    "status": "状态",
}


def _metric_definition_map(definitions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    active = [definition for definition in definitions if definition.get("status") == "active"]
    latest = _latest_rows(active, ("metric_code",), "version")
    return {str(definition["metric_code"]): definition for definition in latest}


def _metric_view(definition: dict[str, Any], value: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(value or {})
    status = _metric_status(row) if value is not None else "unknown"
    data_status = str(row.get("data_status") or "empty")
    unit = str(row.get("unit") or definition.get("unit") or "")
    row.update(
        metric_code=definition.get("metric_code"),
        metric_name=definition.get("metric_name"),
        metric_domain=definition.get("metric_domain"),
        metric_domain_name=_METRIC_DOMAIN_NAMES.get(str(definition.get("metric_domain")), "未归属"),
        unit=unit,
        unit_name=_METRIC_UNIT_NAMES.get(unit, unit),
        formula=definition.get("formula"),
        dimensions=definition.get("dimensions") or {},
        minimum_sample_count=definition.get("minimum_sample_count") or 0,
        metric_version=definition.get("version"),
        metric_value=row.get("metric_value"),
        sample_count=row.get("sample_count"),
        window_start=row.get("window_start"),
        window_end=row.get("window_end"),
        calculated_at=row.get("calculated_at"),
        source_summary=row.get("source_summary") or {},
        data_status=data_status,
        data_status_name=_METRIC_DATA_STATUS_NAMES.get(data_status, "无法判定"),
        assessment_status=status,
        assessment_status_name=_METRIC_STATUS_NAMES[status],
        bucket_size=row.get("bucket_size"),
        bucket_size_name=(
            "5 分钟"
            if row.get("bucket_size") == "5m"
            else "1 小时"
            if row.get("bucket_size") == "1h"
            else str(row.get("bucket_size") or "暂无")
        ),
    )
    return row


def _latest_rows(
    rows: list[dict[str, Any]],
    key_fields: tuple[str, ...],
    time_field: str,
) -> list[dict[str, Any]]:
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        current = latest.get(key)
        if current is None or (row.get(time_field) or datetime.min.replace(tzinfo=UTC)) > (
            current.get(time_field) or datetime.min.replace(tzinfo=UTC)
        ):
            latest[key] = row
    return list(latest.values())


def _metric_trend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[datetime, dict[str, int]] = {}
    for row in rows:
        window_end = row.get("window_end")
        if not isinstance(window_end, datetime):
            continue
        bucket = _bucket_5m(window_end)
        current = buckets.setdefault(
            bucket,
            {"ready": 0, "warning": 0, "failed": 0, "unknown": 0},
        )
        current[_metric_status(row)] += 1
    return [{"window_end": bucket, **values} for bucket, values in sorted(buckets.items())]


def _task_trend(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[datetime, dict[str, int]] = {}
    for event in events:
        occurred_at = event.get("occurred_at")
        if not isinstance(occurred_at, datetime):
            continue
        bucket = _bucket_5m(occurred_at)
        current = buckets.setdefault(
            bucket,
            {"pending": 0, "running": 0, "completed": 0, "failed": 0},
        )
        status = str(event.get("status") or "")
        if status in {"pending", "queued"}:
            current["pending"] += 1
        elif status in {"running", "processing"}:
            current["running"] += 1
        elif status in {"success", "completed", "succeeded"}:
            current["completed"] += 1
        elif status in {"failed", "error", "timeout", "cancelled"}:
            current["failed"] += 1
    return [{"window_end": bucket, **values} for bucket, values in sorted(buckets.items())]


_TASK_STATUS_NAMES = {
    "pending": "待处理",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "timeout": "已超时",
    "cancelled": "已取消",
    "unknown": "未知",
}

_WORKER_STATUS_NAMES = {
    "busy": "忙碌",
    "idle": "空闲",
    "running": "运行中",
    "stale": "延迟",
    "stopped": "已停止",
    "error": "异常",
    "unknown": "未知",
}


def _canonical_task_status(status: Any) -> str:
    value = str(status or "unknown")
    if value in {"queued", "pending"}:
        return "pending"
    if value in {"started", "running", "processing", "retrying"}:
        return "running"
    if value in {"success", "succeeded", "completed"}:
        return "completed"
    if value in {"failed", "error"}:
        return "failed"
    if value == "timeout":
        return "timeout"
    if value in {"canceled", "cancelled"}:
        return "cancelled"
    return "unknown"


def _wait_seconds(task: dict[str, Any], status: str) -> int | None:
    created_at = task.get("created_at")
    if not isinstance(created_at, datetime) or status not in {"pending", "running"}:
        return None
    boundary = task.get("started_at") if status == "running" else utils.utc_now()
    if not isinstance(boundary, datetime):
        boundary = utils.utc_now()
    return max(0, int((boundary - created_at).total_seconds()))


def _indexing_task_view(task: dict[str, Any], tenant_id: int | None) -> dict[str, Any]:
    status = _canonical_task_status(task.get("status"))
    return {
        "task_key": f"indexing-{task['id']}",
        "task_name": f"索引构建 {task['id']}",
        "task_type": "indexing",
        "task_type_name": "索引构建",
        "status": status,
        "status_name": _TASK_STATUS_NAMES[status],
        "progress": task.get("progress"),
        "stage": task.get("current_step"),
        "wait_seconds": _wait_seconds(task, status),
        "worker_code": "indexing",
        "tenant_id": tenant_id,
        "kb_id": task.get("kb_id"),
        "task_id": task.get("id"),
        "run_id": None,
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "attempts": task.get("attempts"),
        "max_attempts": task.get("max_attempts"),
        "error_message": task.get("error_message"),
    }


def _evaluation_task_view(run: dict[str, Any], evaluation_task: dict[str, Any]) -> dict[str, Any]:
    status = _canonical_task_status(run.get("status"))
    question_count = int(run.get("question_count") or 0)
    completed_count = int(run.get("completed_count") or 0)
    failed_count = int(run.get("failed_count") or 0)
    if question_count > 0:
        progress = min(100, round((completed_count + failed_count) / question_count * 100))
    elif status == "completed":
        progress = 100
    else:
        progress = 0
    return {
        "task_key": f"evaluation-{run['id']}",
        "task_name": f"{evaluation_task.get('name') or '自主评测'} · 第 {run.get('run_no')} 次",
        "task_type": "evaluation",
        "task_type_name": "自主评测",
        "status": status,
        "status_name": _TASK_STATUS_NAMES[status],
        "progress": progress,
        "stage": run.get("stage"),
        "wait_seconds": _wait_seconds(run, status),
        "worker_code": "evaluation",
        "tenant_id": evaluation_task.get("tenant_id"),
        "kb_id": evaluation_task.get("kb_id"),
        "task_id": evaluation_task.get("id"),
        "run_id": run.get("id"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "question_count": question_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "conclusion": run.get("conclusion"),
        "error_message": run.get("error_message"),
    }


async def _task_records(scope: int | None) -> list[dict[str, Any]]:
    db = DB.get()
    knowledge_bases = await knowledge_base_db.list(
        db, **({"tenant_id": scope} if scope is not None else {})
    )
    kb_tenants = {int(row["id"]): row.get("tenant_id") for row in knowledge_bases}
    indexing = [
        _indexing_task_view(row, kb_tenants.get(int(row["kb_id"])))
        for row in await indexing_task_db.list(db)
        if int(row["kb_id"]) in kb_tenants
    ]
    evaluation_tasks = await evaluation_task_db.list(
        db, **({"tenant_id": scope} if scope is not None else {})
    )
    evaluation_by_id = {int(row["id"]): row for row in evaluation_tasks}
    evaluation = [
        _evaluation_task_view(row, evaluation_by_id[int(row["task_id"])])
        for row in await evaluation_run_db.list(db)
        if int(row["task_id"]) in evaluation_by_id
    ]
    return sorted(
        [*indexing, *evaluation],
        key=lambda row: row.get("created_at") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )


def _worker_views(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = utils.utc_now()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        code = str(event.get("source_code") or "")
        if (
            code not in {"indexing", "evaluation"}
            and event.get("event_type") != "worker_task_claimed"
        ):
            continue
        grouped.setdefault(code, []).append(event)
    workers: list[dict[str, Any]] = []
    for code, rows in sorted(grouped.items()):
        ordered = sorted(
            rows,
            key=lambda row: row.get("occurred_at") or datetime.min.replace(tzinfo=UTC),
        )
        heartbeats = [row for row in ordered if row.get("event_type") == "worker_heartbeat"]
        last_heartbeat = heartbeats[-1].get("occurred_at") if heartbeats else None
        last_idle = next(
            (row for row in reversed(ordered) if row.get("event_type") == "worker_idle"), None
        )
        last_claimed = next(
            (row for row in reversed(ordered) if row.get("event_type") == "worker_task_claimed"),
            None,
        )
        last_event = ordered[-1]
        if not isinstance(last_heartbeat, datetime) or (now - last_heartbeat).total_seconds() > 60:
            status = "stale"
        elif last_event.get("event_type") == "worker_stopped":
            status = "stopped"
        elif last_event.get("event_type") == "worker_failed":
            status = "error"
        elif last_claimed and (
            not last_idle or last_claimed.get("occurred_at") > last_idle.get("occurred_at")
        ):
            status = "busy"
        elif last_idle:
            status = "idle"
        else:
            status = "running"
        consumed_count = sum(row.get("event_type") == "worker_task_claimed" for row in ordered)
        workers.append(
            {
                "worker_code": code,
                "worker_name": "自主评测 Worker" if code == "evaluation" else "索引构建 Worker",
                "status": status,
                "status_name": _WORKER_STATUS_NAMES[status],
                "consumed_count": consumed_count,
                "capacity_status": "abnormal"
                if status in {"stale", "stopped", "error"}
                else "normal",
                "capacity_name": "消费能力异常"
                if status in {"stale", "stopped", "error"}
                else "消费能力正常",
                "current_task_id": (
                    last_claimed.get("task_id") if status == "busy" and last_claimed else None
                ),
                "last_heartbeat_at": last_heartbeat,
            }
        )
    return workers


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
            summary={
                "event_type": payload.event_type,
                "source_code": payload.source_code,
                "resource_name": payload.payload.get("resource_name"),
            },
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
            [row.get("occurred_at") for row in events if row.get("occurred_at")] or [None]
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
        domain_views = [view for view in views if _collection_domain(view)[0] == domain_code]
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
async def metrics_overview(
    current_user: CurrentUser,
    time_range: str = "1h",
    data_scope: str = "current",
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, end_at = _overview_window(time_range)
    scope = await tenant_scope(current_user)
    if data_scope not in {"current", "platform", "tenant"}:
        raise BusiException("data_scope 必须是 current、platform 或 tenant")
    if data_scope == "platform" and scope is not None:
        raise BusiException("当前角色无权查看平台范围", status_code=403)
    if data_scope == "tenant" and current_user.tenant_id is None:
        raise BusiException("当前未选择租户")
    filters = _scope_filter(scope)
    if data_scope == "platform":
        filters["tenant_id"] = None
    if data_scope == "tenant" and current_user.tenant_id is not None:
        filters["tenant_id"] = current_user.tenant_id
    rows = await value_db.list(
        DB.get(),
        **filters,
        window_end__gte=start_at,
    )
    definitions = _metric_definition_map(await definition_db.list(DB.get()))
    latest_values = _latest_rows(rows, ("metric_code",), "window_end")
    values_by_code = {str(row.get("metric_code")): row for row in latest_values}
    latest = [
        _metric_view(definition, values_by_code.get(metric_code))
        for metric_code, definition in definitions.items()
    ]
    status_distribution = {"ready": 0, "warning": 0, "failed": 0, "unknown": 0}
    domains: dict[str, dict[str, Any]] = {}
    for row in latest:
        status = _metric_status(row)
        status_distribution[status] += 1
        domain_code = str(row.get("metric_domain") or "unknown")
        domain_name = str(row.get("metric_domain_name") or "未归属")
        domain = domains.setdefault(
            domain_code,
            {
                "domain_code": domain_code,
                "domain_name": domain_name,
                "total": 0,
                "ready": 0,
                "warning": 0,
                "failed": 0,
                "unknown": 0,
                "latest_updated_at": None,
            },
        )
        domain["total"] += 1
        domain[status] += 1
        if row.get("window_end") is not None and (
            domain["latest_updated_at"] is None
            or row.get("window_end") > domain["latest_updated_at"]
        ):
            domain["latest_updated_at"] = row.get("window_end")
    for domain in domains.values():
        observed_count = domain["total"] - domain["unknown"]
        domain["healthy_rate"] = domain["ready"] / observed_count if observed_count else None
    concern_count = status_distribution["warning"] + status_distribution["failed"]
    unknown_count = status_distribution["unknown"]
    attention = [
        row["metric_name"]
        for row in latest
        if row["assessment_status"] in {"warning", "failed", "unknown"}
    ]
    return {
        "conclusion": (
            "empty"
            if not rows
            else "success"
            if not concern_count and not unknown_count
            else "partial"
        ),
        "conclusion_text": (
            "当前时间范围暂无有效指标结果"
            if not rows
            else "当前指标结果整体达标"
            if not concern_count and not unknown_count
            else f"当前有 {concern_count + unknown_count} 项指标需要关注"
        ),
        "conclusion_detail": (
            "已发布指标定义，等待真实样本进入统计窗口"
            if not rows and latest
            else "、".join(attention[:2]) + ("等需要关注" if len(attention) > 2 else "")
            if attention
            else "当前未发现需要关注的指标"
        ),
        "total_count": len(latest),
        "status_distribution": status_distribution,
        "trend": _metric_trend(rows),
        "domains": sorted(
            domains.values(),
            key=lambda domain: _METRIC_DOMAIN_ORDER.get(str(domain["domain_code"]), 99),
        ),
        "scope_name": "当前范围"
        if data_scope == "current"
        else "全平台"
        if data_scope == "platform"
        else "当前租户",
        "time_range": time_range,
        "window_start": start_at,
        "window_end": end_at,
        "data_status": "ready" if rows else "empty",
    }


@check_db_connected
async def metric_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    metric_name: str | None = None,
    metric_domain: str | None = None,
    data_scope: str = "current",
    time_range: str = "1h",
    data_status: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, _ = _overview_window(time_range)
    scope = await tenant_scope(current_user)
    if data_scope not in {"current", "platform", "tenant"}:
        raise BusiException("data_scope 必须是 current、platform 或 tenant")
    if data_scope == "platform" and scope is not None:
        raise BusiException("当前角色无权查看平台范围", status_code=403)
    if data_scope == "tenant" and current_user.tenant_id is None:
        raise BusiException("当前未选择租户")
    filters = _scope_filter(scope)
    if data_scope == "platform":
        filters["tenant_id"] = None
    if data_scope == "tenant" and current_user.tenant_id is not None:
        filters["tenant_id"] = current_user.tenant_id
    values = await value_db.list(DB.get(), **filters, window_end__gte=start_at)
    latest_values = _latest_rows(values, ("metric_code",), "window_end")
    values_by_code = {str(row.get("metric_code")): row for row in latest_values}
    definitions = _metric_definition_map(await definition_db.list(DB.get()))
    rows = [
        _metric_view(definition, values_by_code.get(metric_code))
        for metric_code, definition in definitions.items()
    ]
    if metric_name:
        keyword = metric_name.strip().lower()
        rows = [
            row
            for row in rows
            if keyword in str(row.get("metric_name") or "").lower()
            or keyword in str(row.get("metric_code") or "").lower()
        ]
    if metric_domain:
        rows = [row for row in rows if row.get("metric_domain") == metric_domain]
    if data_status:
        rows = [row for row in rows if row.get("data_status") == data_status]
    return _page(rows, page, page_size)


@check_db_connected
async def tasks_overview(current_user: CurrentUser, time_range: str = "1h") -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, end_at = _overview_window(time_range)
    scope = await tenant_scope(current_user)
    tasks = await _task_records(scope)
    tasks = [
        task
        for task in tasks
        if task.get("status") in {"pending", "running"}
        or (isinstance(task.get("created_at"), datetime) and task["created_at"] >= start_at)
    ]
    task_events: list[dict[str, Any]] = []
    for source_type in ("document_index", "evaluation_agent"):
        task_events.extend(
            await event_db.list(
                DB.get(),
                **_scope_filter(scope),
                source_type=source_type,
                occurred_at__gte=start_at,
                limit=10000,
            )
        )
    worker_events = await event_db.list(
        DB.get(),
        **_scope_filter(scope),
        source_type="worker",
        occurred_at__gte=start_at,
        limit=10000,
    )
    workers = _worker_views(worker_events)
    statuses = {status: 0 for status in _TASK_STATUS_NAMES}
    for task in tasks:
        status = str(task.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    waiting = [
        int(task["wait_seconds"])
        for task in tasks
        if task.get("status") == "pending" and task.get("wait_seconds") is not None
    ]
    pending_count = statuses["pending"]
    running_count = statuses["running"]
    failed_count = statuses["failed"] + statuses["timeout"]
    abnormal_workers = sum(worker["status"] in {"stale", "stopped", "error"} for worker in workers)
    long_wait_count = sum(wait_seconds >= 15 * 60 for wait_seconds in waiting)
    if failed_count or abnormal_workers or long_wait_count:
        conclusion = "partial"
        concern_count = failed_count + abnormal_workers + long_wait_count
        conclusion_text = f"任务消费需要关注，{concern_count} 项异常或等待较长"
    elif not tasks:
        conclusion = "idle"
        conclusion_text = "当前时间范围暂无任务，Worker 空闲属于正常状态"
    else:
        conclusion = "healthy"
        conclusion_text = "任务消费整体正常，当前没有持续积压或 Worker 异常"
    oldest_wait = max(waiting) if waiting else None
    return {
        "conclusion": conclusion,
        "conclusion_text": conclusion_text,
        "conclusion_detail": (
            f"待处理 {pending_count} 个，运行中 {running_count} 个，"
            f"异常 Worker {abnormal_workers} 个"
        ),
        "status_distribution": statuses,
        "total_count": len(tasks),
        "pending_count": pending_count,
        "running_count": running_count,
        "failed_count": failed_count,
        "oldest_wait_seconds": oldest_wait,
        "workers": workers,
        "worker_summary": {
            "total": len(workers),
            "busy": sum(worker["status"] == "busy" for worker in workers),
            "idle": sum(worker["status"] == "idle" for worker in workers),
            "abnormal": abnormal_workers,
            "consumed": sum(int(worker["consumed_count"]) for worker in workers),
        },
        "trend": _task_trend(task_events),
        "scope_name": "全平台" if scope is None else "当前租户",
        "time_range": time_range,
        "window_start": start_at,
        "window_end": end_at,
        "data_status": "ready" if tasks or workers else "empty",
    }


@check_db_connected
async def task_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    task_name: str | None = None,
    task_type: str | None = None,
    status: str | None = None,
    worker_code: str | None = None,
    time_range: str = "1h",
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, _ = _overview_window(time_range)
    rows = [
        row
        for row in await _task_records(await tenant_scope(current_user))
        if isinstance(row.get("created_at"), datetime) and row["created_at"] >= start_at
    ]
    if task_name:
        keyword = task_name.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("task_name") or "").lower()]
    if task_type:
        rows = [row for row in rows if row.get("task_type") == task_type]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if worker_code:
        rows = [row for row in rows if row.get("worker_code") == worker_code]
    return _page(rows, page, page_size)


@check_db_connected
async def task_detail(
    current_user: CurrentUser, task_key: str, time_range: str = "24h"
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    task = next(
        (row for row in await _task_records(scope) if row.get("task_key") == task_key),
        None,
    )
    if task is None:
        raise BusiException("任务不存在", status_code=404)
    start_at, end_at = _overview_window(time_range)
    filters = {
        **_scope_filter(scope),
        "occurred_at__gte": start_at,
        "limit": 200,
    }
    if task.get("run_id") is not None:
        filters["run_id"] = task["run_id"]
    else:
        filters["task_id"] = task["task_id"]
    evidence = await event_db.list(DB.get(), **filters)
    return {
        "task": task,
        "evidence": list(reversed(evidence)),
        "time_range": time_range,
        "window_start": start_at,
        "window_end": end_at,
        "data_status": "ready" if evidence else "empty",
    }


@check_db_connected
async def notification_record_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    channel_type: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    time_range: str = "1h",
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    start_at, _ = _overview_window(time_range)
    channels = await channel_db.list(DB.get(), **_scope_filter(scope))
    channel_map = {row["id"]: row for row in channels}
    policies = await policy_db.list(DB.get(), **_scope_filter(scope))
    policy_map = {row["id"]: row for row in policies}
    alerts = await alert_db.list(DB.get(), **_scope_filter(scope))
    alert_map = {row["id"]: row for row in alerts}
    rows = []
    for record in await notification_record_db.list(DB.get(), created_at__gte=start_at):
        if scope is not None and (
            record.get("channel_id") not in channel_map
            or record.get("policy_id") not in policy_map
            or record.get("alert_id") not in alert_map
        ):
            continue
        channel = channel_map.get(record.get("channel_id")) or {}
        policy = policy_map.get(record.get("policy_id")) or {}
        alert = alert_map.get(record.get("alert_id")) or {}
        row = dict(record)
        row.update(
            channel_name=channel.get("channel_name") or "未知渠道",
            channel_type=channel.get("channel_type"),
            policy_name=policy.get("policy_name") or "未关联策略",
            severity=alert.get("severity") or policy.get("severity"),
            severity_name=_ALERT_SEVERITY_NAMES.get(
                str(alert.get("severity") or policy.get("severity")), "全部级别"
            ),
            trigger_scope=_notification_scope_label(
                policy.get("scope") or record.get("receiver_scope") or {}
            ),
            status_name=_NOTIFICATION_STATUS_NAMES.get(str(record.get("status")), "未知状态"),
            failure_summary=(
                str(record.get("failure_category") or "发送失败")
                if record.get("status") == "failed"
                else None
            ),
        )
        rows.append(row)
    if channel_type:
        rows = [row for row in rows if row.get("channel_type") == channel_type]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if severity:
        rows = [row for row in rows if row.get("severity") == severity]
    return _page(rows, page, page_size)


@check_db_connected
async def audit_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    actor_id: str | None = None,
    action: str | None = None,
    result: str | None = None,
    target_id: str | None = None,
    tenant_id: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    rows = await audit_log_db.list(DB.get())
    if scope is not None:
        rows = [
            row
            for row in rows
            if str((row.get("request_summary") or {}).get("tenant_id")) == str(scope)
        ]
    if tenant_id is not None:
        rows = [
            row
            for row in rows
            if str((row.get("request_summary") or {}).get("tenant_id")) == str(tenant_id)
        ]
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
    if start_at:
        rows = [row for row in rows if row.get("created_at") and row["created_at"] >= start_at]
    if end_at:
        rows = [row for row in rows if row.get("created_at") and row["created_at"] <= end_at]
    users = {str(row["id"]): row for row in await user_db.list(DB.get())}
    page_result = _page(rows, page, page_size)
    page_result["items"] = [_audit_view(row, users) for row in page_result["items"]]
    return page_result


def _audit_resource_name(summary: Any) -> str | None:
    if not isinstance(summary, dict):
        return None
    for key in (
        "resource_name",
        "target_name",
        "alert_title",
        "rule_name",
        "channel_name",
        "policy_name",
        "metric_name",
        "task_name",
        "event_name",
        "knowledge_base_name",
        "kb_name",
        "tenant_name",
        "organization_name",
        "document_name",
        "display_name",
        "username",
        "name",
        "title",
    ):
        value = summary.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    for key in ("resource", "target", "after", "before"):
        nested_name = _audit_resource_name(summary.get(key))
        if nested_name:
            return nested_name
    return None


def _audit_view(row: dict[str, Any], users: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item = dict(row)
    actor = users.get(str(row.get("actor_id")))
    summary = _sanitize_event_context(row.get("request_summary") or {})
    tenant_id = summary.get("tenant_id") if isinstance(summary, dict) else None
    action_name = str(row.get("action_cn") or "")
    if not action_name or action_name == "其他操作":
        action_name = audit_service.action_cn(str(row.get("action") or ""))
    item.update(
        action_cn=action_name,
        actor_name=(actor or {}).get("display_name")
        or (actor or {}).get("username")
        or ("系统" if row.get("actor_id") == "system" else row.get("actor_id")),
        result_name="已完成" if row.get("result") == "success" else "执行失败",
        target_type_name={
            "monitor_alert": "告警实例",
            "monitor_metric_rule": "告警规则",
            "monitor_notification_channel": "通知渠道",
            "monitor_notification_policy": "通知策略",
            "monitor_event": "监控事件",
            "monitor_analysis_conversation": "分析会话",
        }.get(str(row.get("target_type")), "监控资源"),
        tenant_id=tenant_id,
        tenant_scope_name=f"租户 {tenant_id}" if tenant_id is not None else "全平台",
        resource_name=_audit_resource_name(summary),
        request_summary=summary,
        operation_description=(
            f"{action_name}：{row.get('target_id') or '未指定资源'}"
        ),
    )
    return item


@check_db_connected
async def audit_options(current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    rows = await audit_log_db.list(DB.get())
    if scope is not None:
        rows = [
            row
            for row in rows
            if str((row.get("request_summary") or {}).get("tenant_id")) == str(scope)
        ]
    users = {str(row["id"]): row for row in await user_db.list(DB.get())}
    views = [_audit_view(row, users) for row in rows]
    return {
        "actors": sorted(
            {
                (str(row.get("actor_id") or ""), str(row.get("actor_name") or ""))
                for row in views
                if row.get("actor_id")
            }
        ),
        "actions": sorted(
            {
                (str(row.get("action") or ""), str(row.get("action_cn") or "其他操作"))
                for row in views
                if row.get("action")
            }
        ),
        "targets": sorted(
            {str(row.get("target_id")) for row in views if row.get("target_id")}
        ),
        "tenant_scopes": sorted(
            {
                (int(row["tenant_id"]), str(row["tenant_scope_name"]))
                for row in views
                if row.get("tenant_id") is not None
            }
        ),
    }


@check_db_connected
async def audit_detail(current_user: CurrentUser, audit_id: int) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    row = await audit_log_db.get(DB.get(), id=audit_id)
    if not row:
        raise BusiException("审计记录不存在", status_code=404)
    row_scope = (row.get("request_summary") or {}).get("tenant_id")
    if scope is not None and str(row_scope) != str(scope):
        raise BusiException("审计记录不存在", status_code=404)
    users = {str(item["id"]): item for item in await user_db.list(DB.get())}
    return _audit_view(row, users)


@check_db_connected
async def analysis_overview(
    current_user: CurrentUser,
    time_range: str = "1h",
    scope_key: str = "platform",
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, end_at = _overview_window(time_range)
    scope = await tenant_scope(current_user)
    definitions = _metric_definition_map(await definition_db.list(DB.get()))
    alert_rows = await alert_db.list(DB.get(), **_scope_filter(scope))
    alerts = [
        _alert_view(row, definitions)
        for row in alert_rows
        if row.get("status") in {"firing", "acknowledged"}
        and row.get("last_fired_at")
        and row["last_fired_at"] >= start_at
    ]
    alert_ids = {int(row["id"]) for row in alerts}
    evidence_rows = [
        row
        for row in await alert_evidence_db.list(DB.get())
        if int(row.get("alert_id") or 0) in alert_ids
    ]
    metric_values = await value_db.list(
        DB.get(),
        **_scope_filter(scope),
        window_end__gte=start_at,
    )
    latest_metrics: dict[str, dict[str, Any]] = {}
    for row in metric_values:
        code = str(row.get("metric_code") or "")
        if code not in latest_metrics or row.get("window_end") > latest_metrics[code].get(
            "window_end"
        ):
            latest_metrics[code] = row

    evidence: list[dict[str, Any]] = []
    for alert in alerts:
        evidence.append(
            {
                "id": f"alert-{alert['id']}",
                "evidence_type": "alert",
                "evidence_type_name": "告警",
                "title": alert.get("alert_title"),
                "summary": (
                    f"{alert.get('resource_name')} · {alert.get('status_name')} · "
                    f"{alert.get('severity_name')}"
                ),
                "evidence_level": "direct",
                "evidence_level_name": "直接证据",
                "occurred_at": alert.get("last_fired_at"),
                "target_id": str(alert["id"]),
            }
        )
        metric = latest_metrics.get(str(alert.get("metric_code") or ""))
        if metric:
            definition = definitions.get(str(alert.get("metric_code"))) or {}
            evidence.append(
                {
                    "id": f"metric-{metric['id']}",
                    "evidence_type": "metric",
                    "evidence_type_name": "指标",
                    "title": definition.get("metric_name") or alert.get("metric_code"),
                    "summary": (
                        f"当前值 {metric.get('metric_value')} · 样本 {metric.get('sample_count')}"
                    ),
                    "evidence_level": "direct",
                    "evidence_level_name": "直接证据",
                    "occurred_at": metric.get("window_end"),
                    "target_id": str(metric["id"]),
                }
            )
    evidence_type_names = {
        "event": "事件",
        "task": "任务",
        "evaluation": "评测运行",
        "version": "版本",
        "trace": "Trace",
        "metric": "指标",
        "alert": "告警",
    }
    for row in evidence_rows:
        evidence_type = str(row.get("evidence_type") or "event")
        level = "context" if evidence_type in {"trace", "version"} else "associated"
        evidence.append(
            {
                "id": f"{evidence_type}-{row.get('evidence_id')}",
                "evidence_type": evidence_type,
                "evidence_type_name": evidence_type_names.get(evidence_type, "事件"),
                "title": row.get("evidence_id"),
                "summary": row.get("summary") or "已关联结构化监控事实",
                "evidence_level": level,
                "evidence_level_name": "上下文证据" if level == "context" else "关联证据",
                "occurred_at": row.get("occurred_at") or row.get("created_at"),
                "target_id": str(row.get("evidence_id") or ""),
            }
        )
    deduplicated = {str(item["id"]): item for item in evidence}
    evidence = sorted(
        deduplicated.values(),
        key=lambda item: item.get("occurred_at") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )[:50]

    impacts = []
    seen_resources = set()
    for alert in alerts:
        resource_name = str(alert.get("resource_name") or "未知资源")
        if resource_name in seen_resources:
            continue
        seen_resources.add(resource_name)
        impact_status = "confirmed" if alert.get("severity") == "critical" else "pending"
        impacts.append(
            {
                "resource_name": resource_name,
                "monitor_domain": alert.get("monitor_domain"),
                "monitor_domain_name": alert.get("monitor_domain_name"),
                "impact_status": impact_status,
                "impact_status_name": (
                    "已确认影响" if impact_status == "confirmed" else "待验证影响"
                ),
                "detail": f"关联 {alert.get('severity_name')}告警：{alert.get('alert_title')}",
            }
        )
    suggestions = []
    for index, alert in enumerate(alerts[:3], start=1):
        module = "tasks" if alert.get("monitor_domain") in {"tasks", "evaluation"} else "metrics"
        suggestions.append(
            {
                "priority": index,
                "title": f"核查{alert.get('resource_name')}的运行事实和最近变化",
                "detail": "仅核查已授权证据，不自动修改配置或执行任务。",
                "evidence_refs": [f"alert-{alert['id']}", str(alert.get("metric_code") or "")],
                "confirmation_status": "manual_confirmation",
                "confirmation_status_name": "人工确认",
                "target_module": module,
                "target_label": "查看任务" if module == "tasks" else "查看指标",
            }
        )
    context = {
        "role": "tenant_admin" if scope is not None else "platform_super_admin",
        "alerts": alerts,
        "evidence": evidence,
        "impacts": impacts,
        "timeline": evidence,
        "suggestions": suggestions,
    }
    try:
        result = await MonitoringAgent().build_overview(context=context)
    except Exception as exc:
        LOG.exception("自主监控Agent overview failed")
        result = {
            "incident_id": f"INC-{alerts[0]['id']}" if alerts else None,
            "analysis_status": "unavailable" if alerts else "not_required",
            "attention_status": "manual_confirmation" if alerts else "none",
            "confidence": None,
            "conclusion": "分析暂不可用" if alerts else "当前范围暂无需要分析的异常",
            "conclusion_detail": "原始告警和证据仍可查询，请稍后重试分析。",
            "alerts": alerts,
            "impacts": impacts,
            "evidence": evidence,
            "timeline": evidence,
            "suggestions": [],
            "agent": "自主监控Agent",
            "error": type(exc).__name__,
        }
    result.update(
        scope_key=scope_key,
        scope_name="当前租户" if scope is not None else "全平台",
        time_range=time_range,
        window_start=start_at,
        window_end=end_at,
        last_updated=end_at,
        data_status="ready" if alerts else "empty",
    )
    return result


@check_db_connected
async def events_overview(current_user: CurrentUser, time_range: str = "1h") -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, end_at = _overview_window(time_range)
    scope = await tenant_scope(current_user)
    events = _visible_events(
        await event_db.list(
            DB.get(),
            **_scope_filter(scope),
            occurred_at__gte=start_at,
        )
    )
    abnormal_statuses = {"failed", "error", "timeout", "stopped"}
    abnormal_count = sum(1 for event in events if event.get("status") in abnormal_statuses)
    source_counts = {source: 0 for source in _EVENT_SOURCE_NAMES}
    for event in events:
        source_counts[_event_source_category(event)] += 1
    alert_related_count = source_counts["alert"]
    occurred_times = [
        event["occurred_at"] for event in events if isinstance(event.get("occurred_at"), datetime)
    ]
    if not events:
        conclusion = "暂无事件"
        conclusion_detail = "当前时间范围内暂无监控事件。"
    elif abnormal_count or alert_related_count:
        conclusion = "需要关注"
        conclusion_detail = (
            f"当前共记录 {len(events)} 条事件，其中异常事件 {abnormal_count} 条，"
            f"告警关联事件 {alert_related_count} 条。"
        )
    else:
        conclusion = "运行正常"
        conclusion_detail = f"当前共记录 {len(events)} 条事件，未发现异常或告警关联事件。"
    return {
        "conclusion": conclusion,
        "conclusion_detail": conclusion_detail,
        "total_count": len(events),
        "abnormal_count": abnormal_count,
        "alert_related_count": alert_related_count,
        "latest_event_at": max(occurred_times) if occurred_times else None,
        "trend": _event_trend(events),
        "source_distribution": [
            {
                "source_category": source,
                "source_name": _EVENT_SOURCE_NAMES[source],
                "count": source_counts[source],
                "color": _EVENT_SOURCE_COLORS[source],
            }
            for source in _EVENT_SOURCE_NAMES
        ],
        "scope_name": "平台范围" if scope is None else "当前租户",
        "time_range": time_range,
        "window_start": start_at,
        "window_end": end_at,
        "data_status": "ready" if events else "empty",
    }


@check_db_connected
async def alerts_overview(current_user: CurrentUser, time_range: str = "1h") -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, end_at = _overview_window(time_range)
    scope = await tenant_scope(current_user)
    alerts = await alert_db.list(DB.get(), **_scope_filter(scope))
    window_alerts = [
        alert
        for alert in alerts
        if (isinstance(alert.get("last_fired_at"), datetime) and alert["last_fired_at"] >= start_at)
        or alert.get("status") not in {"resolved", "closed"}
    ]
    unresolved = [alert for alert in alerts if alert.get("status") not in {"resolved", "closed"}]
    severity_distribution = {severity: 0 for severity in _ALERT_SEVERITY_NAMES}
    for alert in unresolved:
        severity = str(alert.get("severity") or "unknown")
        severity_distribution[severity] = severity_distribution.get(severity, 0) + 1
    now = utils.utc_now()
    durations = [
        int((now - alert["first_fired_at"]).total_seconds())
        for alert in unresolved
        if isinstance(alert.get("first_fired_at"), datetime)
    ]
    unacknowledged_count = sum(1 for alert in unresolved if not alert.get("acknowledged_at"))
    critical_count = severity_distribution["critical"]
    if unresolved:
        conclusion = "需要处理"
        conclusion_text = (
            f"{len(unresolved)} 条告警未恢复，{critical_count} 条严重告警，"
            f"{unacknowledged_count} 条待确认"
        )
        conclusion_detail = "请优先处理持续时间较长和严重级别告警。"
    else:
        conclusion = "当前正常"
        conclusion_text = "当前范围暂无未恢复告警"
        conclusion_detail = "已恢复和已关闭告警可在告警明细中追溯。"
    return {
        "conclusion": conclusion,
        "conclusion_text": conclusion_text,
        "conclusion_detail": conclusion_detail,
        "total_count": len(window_alerts),
        "unresolved_count": len(unresolved),
        "unacknowledged_count": unacknowledged_count,
        "critical_count": critical_count,
        "longest_duration_seconds": max(durations) if durations else None,
        "lifecycle": {
            "firing": sum(1 for alert in alerts if alert.get("status") == "firing"),
            "acknowledged": sum(1 for alert in alerts if alert.get("status") == "acknowledged"),
            "resolved": sum(
                1
                for alert in alerts
                if isinstance(alert.get("resolved_at"), datetime)
                and alert["resolved_at"] >= start_at
            ),
            "closed": sum(
                1
                for alert in alerts
                if isinstance(alert.get("closed_at"), datetime) and alert["closed_at"] >= start_at
            ),
        },
        "trend": _alert_overview_trend(alerts, start_at, end_at),
        "severity_distribution": [
            {
                "severity": severity,
                "severity_name": _ALERT_SEVERITY_NAMES[severity],
                "count": severity_distribution[severity],
                "color": _ALERT_SEVERITY_COLORS[severity],
            }
            for severity in _ALERT_SEVERITY_NAMES
        ],
        "scope_name": "平台范围" if scope is None else "当前租户",
        "time_range": time_range,
        "window_start": start_at,
        "window_end": end_at,
        "data_status": "ready" if window_alerts else "empty",
    }


@check_db_connected
async def event_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    event_type: str | None = None,
    monitor_domain: str | None = None,
    resource_name: str | None = None,
    association_id: str | None = None,
    time_range: str = "1h",
    status: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, _ = _overview_window(time_range)
    filters = {
        **_scope_filter(await tenant_scope(current_user)),
        "occurred_at__gte": start_at,
    }
    rows = [_event_view(row) for row in _visible_events(await event_db.list(DB.get(), **filters))]
    if event_type:
        rows = [
            row
            for row in rows
            if row.get("event_type_code") == event_type or row.get("event_type") == event_type
        ]
    if monitor_domain:
        rows = [row for row in rows if row.get("monitor_domain") == monitor_domain]
    if resource_name:
        keyword = resource_name.strip().lower()
        rows = [
            row
            for row in rows
            if keyword in str(row.get("resource_name") or "").lower()
            or keyword in str(row.get("source_code") or "").lower()
        ]
    if association_id:
        keyword = association_id.strip().lower()
        association_fields = ("event_id", "trace_id", "request_id", "task_id", "run_id")
        rows = [
            row
            for row in rows
            if any(keyword in str(row.get(field) or "").lower() for field in association_fields)
        ]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    return _page(rows, page, page_size)


@check_db_connected
async def event_detail(current_user: CurrentUser, event_id: str) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    event = await event_db.get(
        DB.get(),
        **_scope_filter(await tenant_scope(current_user)),
        event_id=event_id,
    )
    if not event or event.get("event_type") == "worker_idle":
        raise BusiException("事件不存在", status_code=404)
    view = _event_view(event, include_context=True)
    return {
        "event": view,
        "context": view.pop("payload", {}),
        "associations": {
            "event_id": event.get("event_id"),
            "trace_id": event.get("trace_id"),
            "request_id": event.get("request_id"),
            "task_id": event.get("task_id"),
            "run_id": event.get("run_id"),
        },
        "data_status": event.get("data_status") or "ready",
    }


@check_db_connected
async def alert_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    status: str | None = None,
    severity: str | None = None,
    monitor_domain: str | None = None,
    resource_name: str | None = None,
    time_range: str = "1h",
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, _ = _overview_window(time_range)
    definitions = _metric_definition_map(await definition_db.list(DB.get()))
    rows = [
        _alert_view(row, definitions)
        for row in await alert_db.list(
            DB.get(),
            **_scope_filter(await tenant_scope(current_user)),
            last_fired_at__gte=start_at,
        )
    ]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if severity:
        rows = [row for row in rows if row.get("severity") == severity]
    if monitor_domain:
        rows = [row for row in rows if row.get("monitor_domain") == monitor_domain]
    if resource_name:
        keyword = resource_name.strip().lower()
        rows = [
            row
            for row in rows
            if keyword in str(row.get("resource_name") or "").lower()
            or keyword in str(row.get("resource_code") or "").lower()
        ]
    return _page(rows, page, page_size)


@check_db_connected
async def alert_detail(current_user: CurrentUser, alert_id: int) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    alert = await alert_db.get(
        DB.get(),
        id=alert_id,
        **_scope_filter(await tenant_scope(current_user)),
    )
    if not alert:
        raise BusiException("告警不存在", status_code=404)
    definitions = _metric_definition_map(await definition_db.list(DB.get()))
    rule = await rule_db.get(DB.get(), id=alert.get("rule_id"))
    evidence = await alert_evidence_db.list(DB.get(), alert_id=alert_id)
    audits = [
        row
        for row in await audit_log_db.list(DB.get())
        if str(row.get("target_id")) == str(alert_id)
        and str(row.get("action") or "").startswith("monitor_alert_")
    ]
    action_names = {
        "monitor_alert_acknowledge": "确认告警",
        "monitor_alert_suppress": "抑制告警",
        "monitor_alert_close": "关闭告警",
        "monitor_alert_note": "添加备注",
        "monitor_alert_resolve": "恢复告警",
    }
    actions = [
        {**row, "action_cn": action_names.get(str(row.get("action")), row.get("action"))}
        for row in audits[:50]
    ]
    return {
        "alert": _alert_view(alert, definitions),
        "rule": _rule_view(rule, definitions) if rule else None,
        "evidence": evidence,
        "actions": actions,
        "data_status": "ready",
    }


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
async def metric_detail(
    current_user: CurrentUser,
    metric_code: str,
    time_range: str = "1h",
    data_scope: str = "current",
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    start_at, end_at = _overview_window(time_range)
    scope = await tenant_scope(current_user)
    if data_scope == "platform" and scope is not None:
        raise BusiException("当前角色无权查看平台范围", status_code=403)
    if data_scope == "tenant" and current_user.tenant_id is None:
        raise BusiException("当前未选择租户")
    filters = _scope_filter(scope)
    if data_scope == "tenant":
        filters["tenant_id"] = current_user.tenant_id
    definitions = _metric_definition_map(await definition_db.list(DB.get()))
    definition = definitions.get(metric_code)
    if definition is None:
        raise BusiException("指标定义不存在", status_code=404)
    values = await value_db.list(
        DB.get(),
        **filters,
        metric_code=metric_code,
        window_end__gte=start_at,
    )
    latest = max(values, key=lambda row: row["window_end"]) if values else None
    rules = await rule_db.list(DB.get(), metric_code=metric_code, enabled=True)
    rule = max(rules, key=lambda row: int(row.get("version") or 0)) if rules else None
    alerts = await alert_db.list(DB.get(), **filters, metric_code=metric_code)
    return {
        "metric": _metric_view(definition, latest),
        "threshold": (
            {
                "warning_threshold": rule.get("warning_threshold"),
                "critical_threshold": rule.get("critical_threshold"),
                "recovery_threshold": rule.get("recovery_threshold"),
                "minimum_sample_count": rule.get("minimum_sample_count"),
                "consecutive_periods": rule.get("consecutive_periods"),
                "version": rule.get("version"),
            }
            if rule
            else None
        ),
        "source_summary": latest.get("source_summary") if latest else {},
        "trend": values[-200:],
        "alerts": alerts[:20],
        "time_range": time_range,
        "window_start": start_at,
        "window_end": end_at,
        "data_status": "ready" if values else "empty",
    }


@check_db_connected
async def create_rule(payload: MetricRuleRequest, current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    db = DB.get()
    existing = await rule_db.list(
        db,
        metric_code=payload.metric_code,
        scope_type=payload.scope_type,
    )
    version = max((int(row.get("version") or 0) for row in existing), default=0) + 1
    async with db.transaction():
        for row in existing:
            if row.get("enabled"):
                await rule_db.update_(db, {"enabled": False}, id=row["id"])
        rule_id = await rule_db.insert_(
            db,
            **payload.model_dump(),
            version=version,
            effective_at=utils.utc_now(),
            created_by=current_user.user_id,
        )
        created = await rule_db.get(db, id=rule_id)
        await audit_service.record(
            db,
            action="monitor_rule_created",
            target_type="monitor_metric_rule",
            target_id=rule_id,
            summary={"metric_code": payload.metric_code, "version": version},
        )
        return created


@check_db_connected
async def list_rules(current_user: CurrentUser) -> list[dict[str, Any]]:
    await require_monitoring_access(current_user)
    return await rule_db.list(DB.get(), enabled=True)


@check_db_connected
async def rules_overview(current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    rules = _latest_rule_versions(await rule_db.list(DB.get()))
    enabled_count = sum(1 for rule in rules if rule.get("enabled"))
    disabled_count = len(rules) - enabled_count
    return {
        "conclusion": "规则正常" if enabled_count else "暂无启用规则",
        "conclusion_text": (
            f"当前 {enabled_count} 条规则已启用，{disabled_count} 条规则停用"
            if rules
            else "当前范围暂无告警规则"
        ),
        "conclusion_detail": "规则变更会生成版本并写入审计记录，生效范围按权限控制。",
        "total_count": len(rules),
        "enabled_count": enabled_count,
        "disabled_count": disabled_count,
        "data_status": "ready" if rules else "empty",
    }


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
                    summary={
                        "metric_code": rule["metric_code"],
                        "reason": decision.reason,
                        "tenant_id": recovered.get("tenant_id"),
                        "resource_name": recovered.get("alert_title"),
                    },
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
            summary={
                "metric_code": rule["metric_code"],
                "severity": decision.severity,
                "tenant_id": alert.get("tenant_id"),
                "resource_name": alert.get("alert_title"),
            },
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
        summary={
            "event_type": event_type,
            "resource_name": alert.get("alert_title"),
        },
    )


@check_db_connected
async def alert_action(
    alert_id: int,
    action: str,
    current_user: CurrentUser,
    note: str | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    filters = {"id": alert_id, **_scope_filter(await tenant_scope(current_user))}
    alert = await alert_db.get(DB.get(), **filters)
    if not alert:
        raise BusiException("告警不存在", status_code=404)
    now = utils.utc_now()
    values = {"updated_at": now}
    if action == "acknowledge":
        if alert.get("status") != "firing":
            raise BusiException("当前状态不能确认告警")
        values.update(
            status="acknowledged", acknowledged_by=current_user.user_id, acknowledged_at=now
        )
    elif action == "resolve":
        if alert.get("status") not in {"firing", "acknowledged"}:
            raise BusiException("当前状态不能恢复告警")
        values.update(status="resolved", resolved_at=now)
    elif action == "close":
        if alert.get("status") not in {"firing", "acknowledged", "resolved"}:
            raise BusiException("当前状态不能关闭告警")
        values.update(status="closed", closed_at=now)
    elif action in {"suppress", "note"}:
        if action == "suppress" and alert.get("status") not in {"firing", "acknowledged"}:
            raise BusiException("当前状态不能抑制告警")
        if action == "note" and alert.get("status") == "closed":
            raise BusiException("已关闭告警仅支持查看")
        if not note or not note.strip():
            raise BusiException("请填写操作原因")
    else:
        raise BusiException("不支持的告警操作")
    async with DB.get().transaction():
        if action not in {"suppress", "note"}:
            await alert_db.update_(DB.get(), values, id=alert_id)
        updated = await alert_db.get(DB.get(), id=alert_id)
        await audit_service.record(
            DB.get(),
            action=f"monitor_alert_{action}",
            target_type="monitor_alert",
            target_id=alert_id,
            summary={
                "status": updated.get("status"),
                "note": note.strip() if note else None,
                "tenant_id": updated.get("tenant_id"),
                "resource_name": updated.get("alert_title"),
            },
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
        rows = [row for row in rows if normalized in str(row.get(name_field) or "").lower()]
    return _page(rows, page, page_size)


def _notification_scope_label(scope: dict[str, Any]) -> str:
    scope_type = str(scope.get("scope_type") or scope.get("type") or "platform")
    domain = str(scope.get("monitor_domain") or scope.get("domain") or "")
    scope_name = {
        "platform": "全平台",
        "tenant": "当前租户",
        "duty_group": "监控值班组",
    }.get(scope_type, scope_type)
    if domain:
        return f"{scope_name} / {_METRIC_DOMAIN_NAMES.get(domain, domain)}"
    return scope_name


def _channel_view(channel: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    row = dict(channel)
    related = [record for record in records if record.get("channel_id") == channel.get("id")]
    latest = related[0] if related else None
    row.update(
        channel_type_name={"in_app": "站内通知", "webhook": "Webhook"}.get(
            str(channel.get("channel_type")), str(channel.get("channel_type") or "未知渠道")
        ),
        status_name="启用" if channel.get("status") == "enabled" else "停用",
        receiver_scope_name=_notification_scope_label(channel.get("receiver_scope") or {}),
        latest_sent_at=(latest.get("sent_at") or latest.get("created_at")) if latest else None,
        latest_status=latest.get("status") if latest else None,
        latest_status_name=(
            _NOTIFICATION_STATUS_NAMES.get(str(latest.get("status")), "未知状态")
            if latest
            else "暂无发送"
        ),
        failed_count=sum(1 for record in related if record.get("status") == "failed"),
    )
    row.pop("endpoint_ref", None)
    return row


def _policy_view(
    policy: dict[str, Any],
    links: list[dict[str, Any]],
    channel_map: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    row = dict(policy)
    channel_names = [
        channel_map[link["channel_id"]].get("channel_name")
        for link in links
        if link.get("policy_id") == policy.get("id") and link.get("channel_id") in channel_map
    ]
    event_names = {
        "firing": "触发",
        "ongoing": "持续",
        "recovery": "恢复",
    }
    row.update(
        severity_name=_ALERT_SEVERITY_NAMES.get(str(policy.get("severity")), "全部级别"),
        scope_name=_notification_scope_label(policy.get("scope") or {}),
        event_type_names=[
            event_names.get(str(event_type), str(event_type))
            for event_type in policy.get("event_types") or []
        ],
        channel_names=[str(name) for name in channel_names if name],
        status_name="启用" if policy.get("status") == "enabled" else "停用",
    )
    return row


@check_db_connected
async def rule_page(
    current_user: CurrentUser,
    page: int,
    page_size: int,
    rule_name: str | None = None,
    monitor_domain: str | None = None,
    severity: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    definitions = _metric_definition_map(await definition_db.list(DB.get()))
    rows = [
        _rule_view(rule, definitions)
        for rule in _latest_rule_versions(await rule_db.list(DB.get()))
    ]
    if rule_name:
        keyword = rule_name.strip().lower()
        rows = [
            row
            for row in rows
            if keyword in str(row.get("rule_name") or "").lower()
            or keyword in str(row.get("metric_code") or "").lower()
        ]
    if monitor_domain:
        rows = [row for row in rows if row.get("monitor_domain") == monitor_domain]
    if severity:
        rows = [row for row in rows if row.get("severity") == severity]
    if enabled is not None:
        rows = [row for row in rows if bool(row.get("enabled")) is enabled]
    return _page(rows, page, page_size)


@check_db_connected
async def update_rule(
    rule_id: int, payload: MetricRuleRequest, current_user: CurrentUser
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    current = await rule_db.get(
        DB.get(),
        id=rule_id,
    )
    if not current:
        raise BusiException("规则不存在", status_code=404)
    return await create_rule(payload, current_user)


@check_db_connected
async def toggle_rule(rule_id: int, current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    current = await rule_db.get(
        DB.get(),
        id=rule_id,
    )
    if not current:
        raise BusiException("规则不存在", status_code=404)
    payload = MetricRuleRequest(
        metric_code=current["metric_code"],
        scope_type=current["scope_type"],
        warning_threshold=current.get("warning_threshold"),
        critical_threshold=current.get("critical_threshold"),
        recovery_threshold=current.get("recovery_threshold"),
        minimum_sample_count=current.get("minimum_sample_count") or 0,
        consecutive_periods=current.get("consecutive_periods") or 1,
        window_seconds=current.get("window_seconds") or 300,
        trigger_type=current.get("trigger_type") or "threshold",
        recovery_periods=current.get("recovery_periods") or 1,
        enabled=not bool(current.get("enabled")),
    )
    return await create_rule(payload, current_user)


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
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    records = await notification_record_db.list(DB.get())
    rows = [
        _channel_view(row, records)
        for row in await channel_db.list(DB.get(), **_scope_filter(scope))
    ]
    if channel_name:
        keyword = channel_name.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("channel_name") or "").lower()]
    return _page(rows, page, page_size)


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
        created = await channel_db.get(DB.get(), id=row_id)
        await audit_service.record(
            DB.get(),
            action="monitor_notification_channel_created",
            target_type="monitor_notification_channel",
            target_id=row_id,
            summary={
                "tenant_id": scope,
                "channel_type": payload.channel_type,
                "resource_name": payload.channel_name,
            },
        )
        return created


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
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    policies = await policy_db.list(DB.get(), **_scope_filter(scope))
    channels = await channel_db.list(DB.get(), **_scope_filter(scope))
    channel_map = {row["id"]: row for row in channels}
    links = await policy_channel_db.list(DB.get())
    rows = [_policy_view(row, links, channel_map) for row in policies]
    if policy_name:
        keyword = policy_name.strip().lower()
        rows = [row for row in rows if keyword in str(row.get("policy_name") or "").lower()]
    return _page(rows, page, page_size)


@check_db_connected
async def notifications_overview(
    current_user: CurrentUser, time_range: str = "1h"
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    start_at, end_at = _overview_window(time_range)
    channels = await channel_db.list(DB.get(), **_scope_filter(scope))
    policies = await policy_db.list(DB.get(), **_scope_filter(scope))
    records = await notification_record_db.list(DB.get(), created_at__gte=start_at)
    if scope is not None:
        channel_ids = {row["id"] for row in channels}
        policy_ids = {row["id"] for row in policies}
        records = [
            row
            for row in records
            if row.get("channel_id") in channel_ids and row.get("policy_id") in policy_ids
        ]
    sent_statuses = {"sent", "success", "completed"}
    sent_count = sum(1 for record in records if record.get("status") in sent_statuses)
    failed_count = sum(1 for record in records if record.get("status") == "failed")
    completed_count = sent_count + failed_count
    success_rate = sent_count / completed_count if completed_count else None
    enabled_channels = sum(1 for row in channels if row.get("status") == "enabled")
    enabled_policies = sum(1 for row in policies if row.get("status") == "enabled")
    if failed_count:
        conclusion = "部分失败"
        conclusion_text = (
            f"{enabled_channels} 个渠道可用，最近发送成功率 {success_rate * 100:.0f}%"
            if success_rate is not None
            else "存在通知发送失败"
        )
        conclusion_detail = f"有 {failed_count} 条通知失败，告警实例仍已保存。"
    elif channels:
        conclusion = "通知正常"
        conclusion_text = (
            f"{enabled_channels} 个渠道可用，最近发送成功率 {success_rate * 100:.0f}%"
            if success_rate is not None
            else f"{enabled_channels} 个渠道可用"
        )
        conclusion_detail = "通知失败不会影响告警实例保存。"
    else:
        conclusion = "暂无渠道"
        conclusion_text = "当前范围暂无通知渠道"
        conclusion_detail = "可按权限新增站内通知或 Webhook 渠道。"
    return {
        "conclusion": conclusion,
        "conclusion_text": conclusion_text,
        "conclusion_detail": conclusion_detail,
        "channel_count": len(channels),
        "enabled_channel_count": enabled_channels,
        "policy_count": len(policies),
        "enabled_policy_count": enabled_policies,
        "sent_count": sent_count,
        "failed_count": failed_count,
        "success_rate": success_rate,
        "scope_name": "平台范围" if scope is None else "当前租户",
        "time_range": time_range,
        "window_start": start_at,
        "window_end": end_at,
        "data_status": "ready" if channels or policies or records else "empty",
    }


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
        await audit_service.record(
            db,
            action="monitor_notification_policy_created",
            target_type="monitor_notification_policy",
            target_id=policy_id,
            summary={
                "tenant_id": scope,
                "severity": payload.severity,
                "resource_name": payload.policy_name,
            },
        )
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
    "event_detail",
    "events_overview",
    "alert_page",
    "alert_detail",
    "alerts_overview",
    "metric_series",
    "create_rule",
    "list_rules",
    "rule_page",
    "rules_overview",
    "update_rule",
    "toggle_rule",
    "apply_rule",
    "alert_action",
    "channel_page",
    "policy_page",
    "list_channels",
    "create_channel",
    "list_policies",
    "create_policy",
    "notification_record_page",
    "notifications_overview",
    "audit_page",
    "audit_options",
    "audit_detail",
    "analysis_overview",
)
