"""自主监控只读事实工具的数据库查询与客户安全数据组装。"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.agents.monitoring.tools.registry import MonitoringToolRegistry
from app.agents.monitoring.correlation import correlate_alert_items
from app.db.base import DB
from app.db.monitoring import (
    alert as alert_db,
)
from app.db.monitoring import (
    event as event_db,
)
from app.db.monitoring import (
    metric_definition as definition_db,
)
from app.db.monitoring import (
    metric_value as value_db,
)
from app.db.monitoring import (
    state_snapshot as snapshot_db,
)

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
_METRIC_DOMAIN_NAMES = {
    "qa": "知识库问答",
    "platform": "平台运行",
    "resource": "平台运行",
    "task": "异步任务",
    "evaluation": "自主评测",
}
_SEVERITY_NAMES = {"critical": "严重", "warning": "警告", "info": "提示"}
_MONITORING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _scope_filter(scope: int | None) -> dict[str, Any]:
    """将可选租户范围转换为 Repository 关键字过滤条件。"""
    return {"tenant_id": scope} if scope is not None else {}


def _in_window(value: datetime | None, start: datetime, end: datetime) -> bool:
    """判断时间是否落在左闭右开的授权窗口内。"""
    return value is not None and start <= value < end


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _display_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    if not isinstance(number, (int, float)):
        return str(number)
    if abs(number) < 0.005:
        number = 0
    return str(Decimal(str(number)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _display_datetime(value: datetime | None) -> str:
    """按客户统一格式展示中国标准时间。"""
    if value is None:
        return "—"
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=_MONITORING_TIMEZONE)
    return current.astimezone(_MONITORING_TIMEZONE).strftime("%Y年%m月%d日 %H:%M:%S")


def _duration_label(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}秒"
    if seconds < 3600:
        return f"{seconds // 60}分钟"
    if seconds < 86400:
        return f"{seconds // 3600}小时"
    return f"{seconds // 86400}天"


def _result(items: list[dict[str, Any]]) -> dict[str, Any]:
    """限制单次事实条数并标记数据是否为空。"""
    return {"items": items[:50], "data_status": "ready" if items else "empty"}


def _metric_definitions(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按指标编码选取最新的启用定义。"""
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("metric_code") or "")
        if not code or row.get("status") != "active":
            continue
        if code not in latest or int(row.get("version") or 0) > int(
            latest[code].get("version") or 0
        ):
            latest[code] = row
    return latest


def _metric_names(rows: list[dict[str, Any]]) -> dict[str, str]:
    """提取可用于客户展示的指标中文业务名称。"""
    return {
        code: str(row.get("metric_name") or "").strip()
        for code, row in _metric_definitions(rows).items()
        if str(row.get("metric_name") or "").strip()
    }


def _customer_alert_title(row: dict[str, Any], metric_names: dict[str, str]) -> str:
    """客户标题使用指标中文业务名，绝不回退暴露内部指标编码。"""
    metric_code = str(row.get("metric_code") or "").strip()
    stored_title = str(row.get("alert_title") or "").strip()
    metric_name = metric_names.get(metric_code)
    if metric_name and (metric_code in stored_title or stored_title.startswith("指标异常：")):
        return f"指标异常：{metric_name}"
    if metric_code and metric_code in stored_title:
        return "指标异常：未配置中文名称"
    return stored_title or "监控告警"


def build_monitoring_tool_registry(*, scope: int | None) -> MonitoringToolRegistry:
    """为指定租户范围构建显式只读监控工具注册表。"""
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
        definition_rows = await definition_db.list(DB.get())
        definitions = _metric_definitions(definition_rows)
        metric_names = _metric_names(definition_rows)
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
            title = _customer_alert_title(row, metric_names)
            definition = definitions.get(str(row.get("metric_code") or "")) or {}
            domain_name = _METRIC_DOMAIN_NAMES.get(
                str(definition.get("metric_domain") or "platform"),
                "平台运行",
            )
            resource_name = (
                "当前知识库"
                if row.get("kb_id") is not None
                else "当前租户"
                if row.get("tenant_id") is not None
                else "全平台"
            )
            duration_end = effective_end if status not in {"firing", "acknowledged"} else window_end
            duration_seconds = max(
                0,
                int((duration_end - row["first_fired_at"]).total_seconds()),
            )
            severity_name = _SEVERITY_NAMES.get(severity, "未知级别")
            status_name = _STATUS_NAMES.get(status, status)
            items.append(
                {
                    "id": f"alert-{row['id']}",
                    "evidence_type": "alert",
                    "evidence_type_name": "告警信息",
                    "title": title,
                    "alert_title": title,
                    "summary": (
                        f"{severity_name} · {status_name} · "
                        f"当前值 {_display_number(row.get('current_value'))}"
                    ),
                    "evidence_level": "direct",
                    "evidence_level_name": "直接证据",
                    "occurred_at": row.get("last_fired_at"),
                    "target_id": str(row["id"]),
                    "status": status,
                    "status_name": status_name,
                    "severity": severity,
                    "severity_name": severity_name,
                    "monitor_domain": definition.get("metric_domain") or "platform",
                    "monitor_domain_name": domain_name,
                    "metric_code": row.get("metric_code"),
                    "metric_name": metric_names.get(str(row.get("metric_code") or ""))
                    or "未配置中文名称",
                    "rule_id": str(row.get("rule_id") or ""),
                    "scope_key": str(row.get("tenant_id") or "platform"),
                    "resource_type": row.get("resource_type"),
                    "resource_code": row.get("resource_code"),
                    "resource_name": resource_name,
                    "current_value": _number(row.get("current_value")),
                    "threshold": _number(row.get("threshold")),
                    "sample_count": int(row.get("sample_count") or 0),
                    "first_fired_at": row.get("first_fired_at"),
                    "last_fired_at": row.get("last_fired_at"),
                    "duration_seconds": duration_seconds,
                    "firing_count": int(row.get("firing_count") or 0),
                    "acknowledged_by_name": row.get("acknowledged_by") or "暂无",
                    "alert_info": (
                        f"{title}；{severity_name} · {domain_name}；资源：{resource_name}"
                    ),
                    "status_detail": (
                        f"{status_name}；当前值：{_display_number(row.get('current_value'))}；"
                        f"阈值：{_display_number(row.get('threshold'))}；"
                        f"样本：{int(row.get('sample_count') or 0)}"
                    ),
                    "time_detail": (
                        f"最近：{_display_datetime(row.get('last_fired_at'))}；"
                        f"首次：{_display_datetime(row.get('first_fired_at'))}；"
                        f"持续：{_duration_label(duration_seconds)}；"
                        f"触发：{int(row.get('firing_count') or 0)} 次；"
                        f"确认：{row.get('acknowledged_by') or '暂无'}"
                    ),
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
                    "evidence_type_name": "指标数据",
                    "title": definition.get("metric_name") or "未配置中文名称",
                    "summary": (
                        f"值 {_number(row.get('metric_value'))}{row.get('unit') or ''} · "
                        f"样本 {row.get('sample_count') or 0} · "
                        f"{_STATUS_NAMES.get(assessment, assessment)}"
                    ),
                    "evidence_level": "direct",
                    "evidence_level_name": "直接证据",
                    "occurred_at": row.get("window_end"),
                    "target_id": code,
                    "metric_code": code,
                    "metric_name": definition.get("metric_name") or "未配置中文名称",
                    "metric_value": _number(row.get("metric_value")),
                    "unit": row.get("unit") or definition.get("unit"),
                    "window_start": row.get("window_start"),
                    "window_end": row.get("window_end"),
                    "scope_key": row.get("scope_key"),
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
                    "evidence_type_name": "运行事件",
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
                    "resource_code": row.get("source_code"),
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
                    "evidence_type_name": "任务事实",
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

    async def get_alert_details(
        *, window_start: datetime, window_end: datetime, scope_key: str, fact_ids: list[str]
    ) -> dict[str, Any]:
        result = await query_alerts(
            window_start=window_start,
            window_end=window_end,
            scope_key=scope_key,
        )
        selected = set(fact_ids)
        return _result([item for item in result["items"] if item["id"] in selected])

    async def correlate_alerts(
        *, window_start: datetime, window_end: datetime, scope_key: str, fact_ids: list[str]
    ) -> dict[str, Any]:
        result = await query_alerts(
            window_start=window_start,
            window_end=window_end,
            scope_key=scope_key,
        )
        selected = set(fact_ids)
        alerts = [item for item in result["items"] if not selected or item["id"] in selected]
        return _result(correlate_alert_items(alerts))

    async def query_metric_series(
        *,
        window_start: datetime,
        window_end: datetime,
        scope_key: str,
        metric_codes: list[str],
        resource_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        selected = set(metric_codes)
        selected_resources = set(resource_codes or [])
        if not selected:
            return _result([])
        definitions = {
            str(item.get("metric_code")): item
            for item in await definition_db.list(DB.get(), status="active")
        }
        rows = await value_db.list(
            DB.get(),
            **_scope_filter(scope),
            scope_key=scope_key,
            metric_code__in=sorted(selected),
            window_end__gte=window_start,
        )
        items = []
        for row in rows:
            if row.get("window_start") is None or row["window_start"] >= window_end:
                continue
            if selected_resources and row.get("scope_key") not in selected_resources:
                continue
            code = str(row.get("metric_code") or "")
            definition = definitions.get(code) or {}
            assessment = str(row.get("assessment_status") or "unknown")
            items.append(
                {
                    "id": f"metric-{row['id']}",
                    "evidence_type": "metric_series",
                    "evidence_type_name": "指标趋势",
                    "title": definition.get("metric_name") or "未配置中文名称",
                    "summary": (
                        f"值 {_display_number(row.get('metric_value'))}{row.get('unit') or ''} · "
                        f"样本 {row.get('sample_count') or 0} · "
                        f"{_STATUS_NAMES.get(assessment, assessment)}"
                    ),
                    "evidence_level": "direct",
                    "evidence_level_name": "直接证据",
                    "occurred_at": row.get("window_end"),
                    "target_id": code,
                    "metric_code": code,
                    "metric_name": definition.get("metric_name") or "未配置中文名称",
                    "metric_value": _number(row.get("metric_value")),
                    "unit": row.get("unit") or definition.get("unit"),
                    "window_start": row.get("window_start"),
                    "window_end": row.get("window_end"),
                    "scope_key": row.get("scope_key"),
                    "assessment_status": assessment,
                    "data_status": str(row.get("data_status") or "unknown"),
                    "sample_count": int(row.get("sample_count") or 0),
                }
            )
        return _result(items)

    async def query_resource_timeline(
        *,
        window_start: datetime,
        window_end: datetime,
        scope_key: str,
        resource_codes: list[str] | None = None,
        trace_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        del scope_key
        selected_resources = set(resource_codes or [])
        selected_traces = set(trace_ids or [])
        if not selected_resources and not selected_traces:
            return _result([])
        rows = []
        if selected_resources:
            rows.extend(
                await event_db.list(
                    DB.get(),
                    **_scope_filter(scope),
                    source_code__in=sorted(selected_resources),
                    occurred_at__gte=window_start,
                )
            )
        if selected_traces:
            rows.extend(
                await event_db.list(
                    DB.get(),
                    **_scope_filter(scope),
                    trace_id__in=sorted(selected_traces),
                    occurred_at__gte=window_start,
                )
            )
        rows_by_id = {row["id"]: row for row in rows}
        items = []
        for row in rows_by_id.values():
            if not _in_window(row.get("occurred_at"), window_start, window_end):
                continue
            status = str(row.get("status") or "unknown")
            items.append(
                {
                    "id": f"event-{row['id']}",
                    "evidence_type": "timeline",
                    "evidence_type_name": "资源时间线",
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
                    "resource_code": row.get("source_code"),
                    "error_category": row.get("error_category"),
                }
            )
        return _result(sorted(items, key=lambda item: item.get("occurred_at") or window_start))

    registry.register("query_health_snapshots", query_health_snapshots)
    registry.register("query_alerts", query_alerts)
    registry.register("query_metrics", query_metrics)
    registry.register("query_events", query_events)
    registry.register("query_tasks", query_tasks)
    registry.register("get_alert_details", get_alert_details)
    registry.register("correlate_alerts", correlate_alerts)
    registry.register("query_metric_series", query_metric_series)
    registry.register("query_resource_timeline", query_resource_timeline)
    return registry


__all__ = ("build_monitoring_tool_registry",)
