"""监控通知发送和失败重试 Worker。"""

from __future__ import annotations

import asyncio

from app.core.common import utils
from app.core.monitoring import emit_gather_event
from app.core.services.platform import audit as audit_service
from app.db.api import check_db_connected
from app.db.base import DB
from app.db.monitoring import notification_channel as channel_db
from app.db.monitoring import notification_record as record_db


async def _deliver(channel: dict, record: dict) -> tuple[bool, str | None]:
    """渠道适配器边界；真实 HTTP/IM 适配器通过此函数注入。"""
    if str(channel.get("endpoint_ref") or "").startswith("mock://success"):
        return True, None
    return False, "CHANNEL_ADAPTER_UNAVAILABLE"


@check_db_connected
async def run_once() -> int:
    records = [
        *await record_db.list(DB.get(), status="pending"),
        *await record_db.list(DB.get(), status="failed"),
    ]
    processed = 0
    for record in records:
        channel = await channel_db.get(DB.get(), id=record.get("channel_id"))
        if record.get("status") == "failed" and int(record.get("retry_count") or 0) >= 3:
            continue
        success, failure_category = await _deliver(channel or {}, record)
        values = {
            "status": "sent" if success else "failed",
            "failure_category": failure_category,
            "retry_count": int(record.get("retry_count") or 0) + (0 if success else 1),
        }
        if success:
            values["sent_at"] = utils.utc_now()
        async with DB.get().transaction():
            await record_db.update_(DB.get(), values, id=record["id"], status=record["status"])
            await audit_service.record(
                DB.get(),
                action="monitor_notification_sent" if success else "monitor_notification_failed",
                target_type="monitor_notification_record",
                target_id=record["id"],
                result="success" if success else "failure",
                summary={
                    "failure_category": failure_category,
                    "retry_count": values["retry_count"],
                },
            )
        processed += 1
    return processed


async def run_forever(stop_event: asyncio.Event, interval_seconds: int = 30) -> None:
    worker_name = "monitoring_notify"
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
