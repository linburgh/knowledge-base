from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.services.monitoring import apply_rule
from app.db import monitor_event as event_db
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
    events = await event_db.list(db, occurred_at__gte=now - timedelta(minutes=5))
    for rule in await rule_db.list(db, enabled=True):
        metric = _aggregate(rule["metric_code"], events, now)
        if metric is None:
            continue
        metric["scope_key"] = "platform"
        metric["tenant_id"] = events[0].get("tenant_id") if events else None
        metric["window_start"] = now - timedelta(minutes=5)
        metric["window_end"] = now
        await value_db.insert_(
            db,
            metric_code=rule["metric_code"],
            metric_version=1,
            scope_key="platform",
            window_start=metric["window_start"],
            window_end=metric["window_end"],
            bucket_size="5m",
            sample_count=metric["sample_count"],
            numerator=metric.get("numerator"),
            denominator=metric.get("denominator"),
            metric_value=metric["metric_value"],
            unit="count" if rule["metric_code"] == "request_count" else "ratio",
            data_status="ready",
            calculated_at=now,
        )
        await apply_rule(rule, metric)
        count += 1
    return count


def _aggregate(metric_code: str, events: list[dict], now: datetime) -> dict | None:
    if metric_code == "request_count":
        return {
            "metric_value": len(events),
            "sample_count": len(events),
            "numerator": len(events),
            "denominator": 1,
        }
    if metric_code == "error_rate":
        errors = sum(event.get("status") in {"error", "failed", "timeout"} for event in events)
        return {
            "metric_value": errors / len(events) if events else 0,
            "sample_count": len(events),
            "numerator": errors,
            "denominator": len(events),
        }
    if metric_code == "p95":
        durations = sorted(
            int(event["duration_ms"]) for event in events if event.get("duration_ms") is not None
        )
        if not durations:
            return None
        index = max(0, min(len(durations) - 1, round(len(durations) * 0.95) - 1))
        return {
            "metric_value": durations[index],
            "sample_count": len(durations),
            "numerator": durations[index],
            "denominator": len(durations),
        }
    return None


async def run_forever(stop_event: asyncio.Event, interval_seconds: int = 60) -> None:
    while not stop_event.is_set():
        await run_once()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
