from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.monitoring import emit_gather_event
from app.core.services.monitoring import apply_rule
from app.core.services.monitoring_rule import evaluate_rule
from app.db import monitor_event as event_db
from app.db import monitor_metric_definition as definition_db
from app.db import monitor_metric_rule as rule_db
from app.db import monitor_metric_value as value_db
from app.db.api import check_db_connected
from app.db.base import DB


@check_db_connected
async def run_once() -> int:
    """聚合入口；规则判断统一委托 monitoring_rule，不在 Worker 内复制规则逻辑。"""
    db = DB.get()
    count = 0
    now = datetime.now(UTC)
    window_end = now.replace(
        minute=now.minute - now.minute % 5,
        second=0,
        microsecond=0,
    )
    window_start = window_end - timedelta(minutes=5)
    events = await event_db.list(
        db,
        occurred_at__gte=window_start,
        occurred_at__lte=window_end,
    )
    events = [event for event in events if event.get("source_code") != "knowledge.qa.monitor_probe"]
    rules = await rule_db.list(db, enabled=True)
    rules_by_code = {
        str(rule["metric_code"]): rule for rule in rules if rule.get("metric_code") is not None
    }
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
        metric = _aggregate(metric_code, events)
        tenant_id = metric.get("tenant_id")
        scope_key = f"tenant:{tenant_id}" if tenant_id is not None else "platform"
        if await value_db.list(
            db,
            metric_code=metric_code,
            scope_key=scope_key,
            window_start=window_start,
            window_end=window_end,
        ):
            continue
        rule = rules_by_code.get(metric_code)
        assessment_status = _assessment_status(rule, metric)
        await value_db.insert_(
            db,
            metric_code=metric_code,
            metric_version=int(definition.get("version") or 1),
            scope_key=scope_key,
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
            bucket_size="5m",
            sample_count=metric["sample_count"],
            numerator=metric.get("numerator"),
            denominator=metric.get("denominator"),
            metric_value=metric.get("metric_value"),
            unit=str(definition.get("unit") or "count"),
            data_status=metric["data_status"],
            assessment_status=assessment_status,
            source_summary=metric.get("source_summary") or {},
            rule_version=int(rule.get("version") or 1) if rule else 1,
            calculated_at=now,
        )
        if rule and metric["data_status"] == "ready":
            metric.update(
                scope_key=scope_key,
                tenant_id=tenant_id,
                window_start=window_start,
                window_end=window_end,
            )
            await apply_rule(rule, metric)
        count += 1
    return count


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


def _aggregate(metric_code: str, events: list[dict]) -> dict[str, Any]:
    terminal_qa = [
        event
        for event in events
        if event.get("event_type") in {"qa_completed", "qa_degraded", "qa_timeout", "qa_failed"}
    ]
    legacy_events = [event for event in events if event.get("event_type") == "qa.request"]
    qa_events = terminal_qa or legacy_events
    qa_tenants = {
        event.get("tenant_id") for event in qa_events if event.get("tenant_id") is not None
    }
    qa_tenant_id = next(iter(qa_tenants)) if len(qa_tenants) == 1 else None
    qa_success = [
        event
        for event in qa_events
        if event.get("event_type") == "qa_completed" or event.get("status") in {"ok", "success"}
    ]
    qa_failed = [
        event
        for event in qa_events
        if event.get("event_type") in {"qa_failed", "qa_timeout"}
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
            "tenant_id": qa_tenant_id,
        }
    if metric_code in {"error_rate", "qa_error_rate"}:
        result = _ratio(len(qa_failed), len(qa_events), len(qa_events))
        result["tenant_id"] = qa_tenant_id
        return result
    if metric_code == "qa_success_rate":
        result = _ratio(len(qa_success), len(qa_events), len(qa_events))
        result["tenant_id"] = qa_tenant_id
        return result
    if metric_code == "qa_timeout_rate":
        timeout_count = sum(
            event.get("event_type") == "qa_timeout" or event.get("status") == "timeout"
            for event in qa_events
        )
        result = _ratio(timeout_count, len(qa_events), len(qa_events))
        result["tenant_id"] = qa_tenant_id
        return result
    if metric_code == "qa_reference_rate":
        cited = sum(
            int((event.get("payload") or {}).get("citation_count") or 0) > 0 for event in qa_success
        )
        result = _ratio(cited, len(qa_success), len(qa_events))
        result["tenant_id"] = qa_tenant_id
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
        result["tenant_id"] = qa_tenant_id
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
