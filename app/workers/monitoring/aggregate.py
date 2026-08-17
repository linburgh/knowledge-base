"""指标聚合和规则执行 Worker。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from numbers import Number
from typing import Any

from app.core.monitoring import emit_gather_event
from app.core.services.monitoring.mgr import apply_rule
from app.core.services.monitoring.rule import evaluate_rule
from app.db.api import check_db_connected
from app.db.base import DB
from app.db.monitoring import event as event_db
from app.db.monitoring import metric_definition as definition_db
from app.db.monitoring import metric_rule as rule_db
from app.db.monitoring import metric_value as value_db


@check_db_connected
async def run_once() -> int:
    """聚合入口；规则判断统一委托 monitoring_rule，不在 Worker 内复制规则逻辑。"""
    now = datetime.now(UTC)
    window_end = now.replace(
        minute=now.minute - now.minute % 5,
        second=0,
        microsecond=0,
    )
    window_start = window_end - timedelta(minutes=5)
    return await _aggregate_window(window_start, window_end, now, apply_alerts=True)


@check_db_connected
async def rebuild_recent(hours: int = 1) -> int:
    """按五分钟窗口重算近期指标；用于规则发布或聚合逻辑升级后的受控回填。"""
    if hours < 1 or hours > 24:
        raise ValueError("hours 必须在 1 到 24 之间")
    now = datetime.now(UTC)
    range_end = now.replace(
        minute=now.minute - now.minute % 5,
        second=0,
        microsecond=0,
    )
    cursor = range_end - timedelta(hours=hours)
    count = 0
    while cursor < range_end:
        window_end = cursor + timedelta(minutes=5)
        count += await _aggregate_window(cursor, window_end, now, apply_alerts=False)
        cursor = window_end
    return count


async def _aggregate_window(
    window_start: datetime,
    window_end: datetime,
    calculated_at: datetime,
    *,
    apply_alerts: bool,
) -> int:
    db = DB.get()
    count = 0
    events = await event_db.list(
        db,
        occurred_at__gte=window_start,
        occurred_at__lte=window_end,
    )
    events = [event for event in events if event.get("source_code") != "knowledge.qa.monitor_probe"]
    rules = await rule_db.list(db, enabled=True)
    rules_by_scope = _latest_rules(rules)
    definitions = [
        definition
        for definition in await definition_db.list(db, status="active")
        if definition.get("metric_code") is not None
    ]
    if not definitions:
        definitions = [
            {
                "metric_code": rule["metric_code"],
                "version": 1,
                "unit": "count" if rule["metric_code"] == "request_count" else "ratio",
                "minimum_sample_count": rule.get("minimum_sample_count") or 0,
            }
            for rule in rules
        ]
    for definition in definitions:
        metric_code = str(definition["metric_code"])
        for tenant_id, scoped_events in _definition_scopes(definition, events):
            scope_type = "tenant" if tenant_id is not None else "platform"
            scope_key = f"tenant:{tenant_id}" if tenant_id is not None else "platform"
            metric = _aggregate(metric_code, scoped_events)
            rule = _rule_for(rules_by_scope, metric_code, scope_type)
            assessment_status = _assessment_status(rule, metric)
            values = {
                "metric_version": int(definition.get("version") or 1),
                "tenant_id": tenant_id,
                "sample_count": metric["sample_count"],
                "numerator": metric.get("numerator"),
                "denominator": metric.get("denominator"),
                "metric_value": metric.get("metric_value"),
                "unit": str(definition.get("unit") or "count"),
                "data_status": metric["data_status"],
                "assessment_status": assessment_status,
                "source_summary": metric.get("source_summary") or {},
                "rule_version": int(rule.get("version") or 1) if rule else 1,
                "calculated_at": calculated_at,
            }
            existing = await value_db.list(
                db,
                metric_code=metric_code,
                scope_key=scope_key,
                window_start=window_start,
                window_end=window_end,
            )
            changed = not existing or _metric_changed(existing[-1], values)
            if existing:
                if changed:
                    await value_db.update_(db, values, id=existing[-1]["id"])
                    count += 1
            else:
                await value_db.insert_(
                    db,
                    metric_code=metric_code,
                    scope_key=scope_key,
                    window_start=window_start,
                    window_end=window_end,
                    bucket_size="5m",
                    **values,
                )
                count += 1
            if changed and apply_alerts and rule and metric["data_status"] == "ready":
                metric.update(
                    scope_key=scope_key,
                    tenant_id=tenant_id,
                    window_start=window_start,
                    window_end=window_end,
                )
                await apply_rule(rule, metric)
    return count


def _metric_changed(existing: dict[str, Any], values: dict[str, Any]) -> bool:
    fields = (
        "metric_version",
        "tenant_id",
        "sample_count",
        "numerator",
        "denominator",
        "metric_value",
        "unit",
        "data_status",
        "assessment_status",
        "source_summary",
        "rule_version",
    )
    for field in fields:
        current = existing.get(field)
        candidate = values.get(field)
        if isinstance(current, Number) and isinstance(candidate, Number):
            if float(current) != float(candidate):
                return True
        elif current != candidate:
            return True
    return False


def _latest_rules(rules: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for rule in rules:
        metric_code = str(rule.get("metric_code") or "")
        scope_type = str(rule.get("scope_type") or "all")
        if not metric_code:
            continue
        key = (metric_code, scope_type)
        if key not in latest or int(rule.get("version") or 1) > int(
            latest[key].get("version") or 1
        ):
            latest[key] = rule
    return latest


def _rule_for(
    rules: dict[tuple[str, str], dict[str, Any]], metric_code: str, scope_type: str
) -> dict[str, Any] | None:
    return rules.get((metric_code, scope_type)) or rules.get((metric_code, "all"))


def _definition_scopes(
    definition: dict[str, Any], events: list[dict[str, Any]]
) -> list[tuple[int | None, list[dict[str, Any]]]]:
    scopes: list[tuple[int | None, list[dict[str, Any]]]] = [(None, events)]
    dimensions = definition.get("dimensions") or {}
    allowed_scopes = dimensions.get("scope", []) if isinstance(dimensions, dict) else []
    if "tenant" not in allowed_scopes:
        return scopes
    tenant_ids = sorted(
        {
            int(event["tenant_id"])
            for event in events
            if event.get("tenant_id") is not None
        }
    )
    scopes.extend(
        (tenant_id, [event for event in events if event.get("tenant_id") == tenant_id])
        for tenant_id in tenant_ids
    )
    return scopes


def _empty(source_count: int = 0) -> dict[str, Any]:
    return {
        "metric_value": None,
        "sample_count": 0,
        "numerator": None,
        "denominator": None,
        "data_status": "empty",
        "source_summary": {"event_count": source_count},
    }


def _ratio(numerator: int, denominator: int, source_count: int) -> dict[str, Any]:
    if denominator == 0:
        return _empty(source_count)
    return {
        "metric_value": numerator / denominator,
        "sample_count": denominator,
        "numerator": numerator,
        "denominator": denominator,
        "data_status": "ready",
        "source_summary": {"event_count": source_count},
    }


def _percentile(values: list[int], percentile: float, source_count: int) -> dict[str, Any]:
    if not values:
        return _empty(source_count)
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(len(ordered) * percentile) - 1))
    value = ordered[index]
    return {
        "metric_value": value,
        "sample_count": len(ordered),
        "numerator": value,
        "denominator": len(ordered),
        "data_status": "ready",
        "source_summary": {"event_count": source_count},
    }


def _latest_payload(events: list[dict], event_type: str) -> dict[str, Any] | None:
    matched = [event for event in events if event.get("event_type") == event_type]
    if not matched:
        return None
    latest = max(
        matched, key=lambda event: event.get("occurred_at") or datetime.min.replace(tzinfo=UTC)
    )
    return latest.get("payload") or {}


def _deduplicate_qa_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        events,
        key=lambda event: event.get("occurred_at") or datetime.min.replace(tzinfo=UTC),
    )
    result: list[dict[str, Any]] = []
    for event in ordered:
        if event.get("event_type") == "qa_degraded" and result:
            previous = result[-1]
            occurred_at = event.get("occurred_at")
            previous_at = previous.get("occurred_at")
            same_scope = (
                event.get("tenant_id") == previous.get("tenant_id")
                and event.get("kb_id") == previous.get("kb_id")
            )
            close_in_time = (
                isinstance(occurred_at, datetime)
                and isinstance(previous_at, datetime)
                and timedelta(0) <= occurred_at - previous_at <= timedelta(seconds=2)
            )
            if (
                previous.get("event_type") in {"qa_failed", "qa_timeout"}
                and same_scope
                and close_in_time
            ):
                result[-1] = event
                continue
        result.append(event)
    return result


def _aggregate(metric_code: str, events: list[dict]) -> dict[str, Any]:
    terminal_qa = _deduplicate_qa_events(
        [
            event
            for event in events
            if event.get("event_type")
            in {"qa_completed", "qa_degraded", "qa_timeout", "qa_failed"}
        ]
    )
    legacy_events = [event for event in events if event.get("event_type") == "qa.request"]
    qa_events = terminal_qa or legacy_events
    qa_success = [
        event
        for event in qa_events
        if event.get("event_type") == "qa_completed" or event.get("status") in {"ok", "success"}
    ]
    qa_failed = [
        event
        for event in qa_events
        if event.get("event_type") in {"qa_failed", "qa_timeout", "qa_degraded"}
        or event.get("status") in {"error", "failed", "timeout"}
    ]
    if metric_code in {"request_count", "qa_request_count"}:
        if not qa_events:
            return _empty()
        return {
            "metric_value": len(qa_events),
            "sample_count": len(qa_events),
            "numerator": len(qa_events),
            "denominator": 1,
            "data_status": "ready",
            "source_summary": {"event_count": len(qa_events)},
        }
    if metric_code in {"error_rate", "qa_error_rate"}:
        result = _ratio(len(qa_failed), len(qa_events), len(qa_events))
        return result
    if metric_code == "qa_success_rate":
        result = _ratio(len(qa_success), len(qa_events), len(qa_events))
        return result
    if metric_code == "qa_timeout_rate":
        timeout_count = sum(
            event.get("event_type") == "qa_timeout"
            or event.get("status") == "timeout"
            or (
                event.get("event_type") == "qa_degraded"
                and (event.get("payload") or {}).get("degraded_reason") == "timeout"
            )
            for event in qa_events
        )
        result = _ratio(timeout_count, len(qa_events), len(qa_events))
        return result
    if metric_code == "qa_reference_rate":
        cited = sum(
            int((event.get("payload") or {}).get("citation_count") or 0) > 0 for event in qa_success
        )
        result = _ratio(cited, len(qa_success), len(qa_events))
        return result
    if metric_code in {"p95", "qa_p95"}:
        result = _percentile(
            [
                int(event["duration_ms"])
                for event in qa_success
                if event.get("duration_ms") is not None
            ],
            0.95,
            len(qa_events),
        )
        return result

    capacity_types = {
        "database_connection_usage": "database_capacity_probe_completed",
        "task_queue_usage": "task_queue_capacity_probe_completed",
        "file_storage_usage": "file_storage_capacity_probe_completed",
        "vector_storage_usage": "vector_storage_capacity_probe_completed",
    }
    if metric_code in capacity_types:
        payload = _latest_payload(events, capacity_types[metric_code])
        usage = payload.get("usage") if payload else None
        if usage is None:
            return _empty()
        return {
            "metric_value": float(usage) / 100,
            "sample_count": 1,
            "numerator": payload.get("used"),
            "denominator": payload.get("capacity"),
            "data_status": "ready",
            "source_summary": {"event_count": 1, "capacity_kind": payload.get("capacity_kind")},
        }
    if metric_code == "vector_service_availability":
        probes = [
            event
            for event in events
            if event.get("event_type") in {"vector_probe_completed", "vector_probe_failed"}
        ]
        success = sum(event.get("event_type") == "vector_probe_completed" for event in probes)
        return _ratio(success, len(probes), len(probes))
    if metric_code == "task_backlog_count":
        payload = _latest_payload(events, "task_backlog_probe_completed")
        pending = payload.get("pending_count") if payload else None
        if pending is None:
            return _empty()
        return {
            "metric_value": int(pending),
            "sample_count": 1,
            "numerator": int(pending),
            "denominator": 1,
            "data_status": "ready",
            "source_summary": {"event_count": 1},
        }
    task_terminal = [
        event
        for event in events
        if event.get("event_type")
        in {
            "document_ingestion_completed",
            "document_ingestion_failed",
            "indexing_completed",
            "indexing_failed",
            "indexing_timeout",
        }
    ]
    if metric_code == "task_success_rate":
        success = sum(
            str(event.get("event_type")).endswith("_completed") for event in task_terminal
        )
        return _ratio(success, len(task_terminal), len(task_terminal))
    if metric_code == "task_wait_p95":
        waits = [
            int((event.get("payload") or {})["wait_duration_ms"])
            for event in events
            if (event.get("payload") or {}).get("wait_duration_ms") is not None
        ]
        return _percentile(waits, 0.95, len(events))
    evaluation_terminal = [
        event
        for event in events
        if event.get("event_type")
        in {
            "evaluation_run_completed",
            "evaluation_run_failed",
            "evaluation_run_timeout",
            "evaluation_run_cancelled",
        }
    ]
    if metric_code == "evaluation_completion_rate":
        completed = sum(
            event.get("event_type") == "evaluation_run_completed" for event in evaluation_terminal
        )
        return _ratio(completed, len(evaluation_terminal), len(evaluation_terminal))
    if metric_code == "evaluation_evidence_completeness":
        completed_runs = {
            event.get("run_id")
            for event in evaluation_terminal
            if event.get("event_type") == "evaluation_run_completed"
            and event.get("run_id") is not None
        }
        evidenced_runs = {
            event.get("run_id")
            for event in events
            if event.get("event_type") == "evaluation_report_persisted"
            and event.get("run_id") in completed_runs
        }
        return _ratio(len(evidenced_runs), len(completed_runs), len(evaluation_terminal))
    return _empty()


def _assessment_status(rule: dict[str, Any] | None, metric: dict[str, Any]) -> str:
    if metric["data_status"] != "ready" or rule is None:
        return "unknown"
    decision = evaluate_rule(rule, metric.get("metric_value"), int(metric["sample_count"]))
    if decision.action == "fire":
        return "failed" if decision.severity == "critical" else "warning"
    if decision.reason in {"insufficient_sample", "rule_disabled"}:
        return "unknown"
    return "ready"


async def run_forever(stop_event: asyncio.Event, interval_seconds: int = 60) -> None:
    worker_name = "monitoring_aggregate"
    await emit_gather_event(
        "worker.lifecycle",
        "worker_started",
        worker_name=worker_name,
        source_code=worker_name,
    )
    try:
        while not stop_event.is_set():
            try:
                await run_once()
                await emit_gather_event(
                    "worker.lifecycle",
                    "worker_heartbeat",
                    worker_name=worker_name,
                    source_code=worker_name,
                )
            except Exception as exc:
                await emit_gather_event(
                    "worker.lifecycle",
                    "worker_failed",
                    worker_name=worker_name,
                    source_code=worker_name,
                    error=exc,
                )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue
    finally:
        await emit_gather_event(
            "worker.lifecycle",
            "worker_stopped",
            worker_name=worker_name,
            source_code=worker_name,
        )
