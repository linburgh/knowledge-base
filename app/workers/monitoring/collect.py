"""周期状态和主动探针采集 Worker。"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from time import monotonic
from typing import Any

import httpx
import sqlalchemy as sa

from app.agents.knowledge.agent import run
from app.config import CONF
from app.core import storage
from app.core.common import utils
from app.core.common.log import LOG
from app.core.monitoring import emit_gather_event, flush_gather_failures
from app.core.services.knowledge_base import qa_config as qa_config_service
from app.db.api import check_db_connected
from app.db.base import DB, database_instance_stats
from app.db.knowledge_base import indexing_task as indexing_task_db
from app.db.knowledge_base import mgr as knowledge_base_db
from app.db.monitoring import event as event_db
from app.db.monitoring import gather_target as target_db
from app.db.monitoring import state_snapshot as snapshot_db
from app.db.platform import evaluation_run as evaluation_run_db
from app.rag.rerank import rerank as rerank_chunks
from app.schemas.agent import AgentContext, AgentTask


async def _upsert_snapshot(
    *,
    resource_type: str,
    resource_code: str,
    status: str,
    status_value: dict[str, Any],
    expires_at,
    error_category: str | None = None,
) -> None:
    db = DB.get()
    now = utils.utc_now()
    values = {
        "resource_type": resource_type,
        "resource_code": resource_code,
        "tenant_id": None,
        "status": status,
        "status_value": status_value,
        "checked_at": now,
        "expires_at": expires_at,
        "error_category": error_category,
        "updated_at": now,
    }
    async with db.transaction():
        existing = await snapshot_db.get(
            db,
            resource_type=resource_type,
            resource_code=resource_code,
            tenant_id=None,
        )
        if existing:
            await snapshot_db.update_(db, values, id=existing["id"])
        else:
            await snapshot_db.insert_(db, **values)


async def _probe_http_dependency(config_group: str, timeout_seconds: float) -> dict[str, Any]:
    if config_group == "chat":
        base_url = CONF.chat.base_url
    elif config_group == "embedding":
        base_url = CONF.embedding.base_url
    elif config_group == "rag":
        if not CONF.rag.rerank_enabled:
            return {"status": "unavailable", "enabled": False}
        ranked = await rerank_chunks(
            "监控知识库能力",
            [
                {"content": "知识库支持文档检索和智能问答。", "score": 0.5},
                {"content": "这是无关的固定探针文本。", "score": 0.4},
            ],
            2,
            timeout_seconds=timeout_seconds,
        )
        if len(ranked) != 2:
            raise RuntimeError("rerank probe result is incomplete")
        return {"status": "healthy", "enabled": True}
    else:
        raise ValueError("unsupported dependency config group")
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get(str(base_url).rstrip("/"))
    if response.status_code >= 500:
        raise RuntimeError(f"dependency returned {response.status_code}")
    return {"status": "healthy", "enabled": True}


async def _probe_worker_status(timeout_seconds: float) -> dict[str, Any]:
    del timeout_seconds
    now = utils.utc_now()
    events = await event_db.list(
        DB.get(),
        event_type="worker_heartbeat",
        occurred_at__gte=now - timedelta(seconds=90),
    )
    workers = {
        str((event.get("payload") or {}).get("worker_name"))
        for event in events
        if (event.get("payload") or {}).get("worker_name")
    }
    expected = {
        "evaluation",
        "indexing",
        "monitoring_aggregate",
        "monitoring_collect",
        "monitoring_notify",
    }
    stale = sorted(expected - workers)
    return {
        "status": "healthy" if not stale else "degraded",
        "worker_count": len(workers),
        "stale_count": len(stale),
    }


async def _probe_task_backlog(timeout_seconds: float) -> dict[str, Any]:
    del timeout_seconds
    db = DB.get()
    indexing = await indexing_task_db.list(db, status="pending")
    evaluation = await evaluation_run_db.list(db, status="pending")
    pending = [*indexing, *evaluation]
    created_values = [row.get("created_at") for row in pending if row.get("created_at")]
    oldest_wait = 0
    if created_values:
        oldest_wait = max(
            0,
            int((utils.utc_now() - min(created_values)).total_seconds()),
        )
    pending_count = len(pending)
    return {
        "status": "degraded" if pending_count > 100 or oldest_wait > 600 else "healthy",
        "pending_count": pending_count,
        "oldest_wait_seconds": oldest_wait,
    }


def _capacity_result(
    *,
    name: str,
    capacity_kind: str,
    used: int,
    capacity: int,
    warning_threshold: float,
    critical_threshold: float,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usage = round((used / capacity) * 100, 2) if capacity > 0 else None
    if usage is None:
        status = "unknown"
    elif usage >= critical_threshold:
        status = "failed"
    elif usage >= warning_threshold:
        status = "degraded"
    else:
        status = "healthy"
    return {
        "status": status,
        "name": name,
        "capacity_kind": capacity_kind,
        "usage": usage,
        "used": used,
        "capacity": capacity if capacity > 0 else None,
        "unit": "%",
        "threshold": warning_threshold,
        **(details or {}),
    }


async def _probe_database_capacity(
    locator: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    stats = await asyncio.wait_for(database_instance_stats(DB.get()), timeout_seconds)
    return _capacity_result(
        name="数据库连接",
        capacity_kind="database_instance",
        used=stats["used"],
        capacity=stats["capacity"],
        warning_threshold=float(locator.get("warning_threshold") or 80),
        critical_threshold=float(locator.get("critical_threshold") or 95),
        details={
            "current_database_connections": stats["current_database_connections"],
            "active_connections": stats["active_connections"],
            "idle_connections": stats["idle_connections"],
            "reserved_connections": stats["reserved_connections"],
            "pool_used": stats["pool_used"],
            "pool_size": stats["pool_size"],
            "pool_idle": stats["pool_idle"],
            "pool_capacity": stats["pool_capacity"],
        },
    )


async def _probe_queue_capacity(
    locator: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    backlog = await _probe_task_backlog(timeout_seconds)
    return _capacity_result(
        name="队列容量",
        capacity_kind="task_queue",
        used=int(backlog["pending_count"]),
        capacity=int(locator.get("capacity_limit") or 0),
        warning_threshold=float(locator.get("warning_threshold") or 80),
        critical_threshold=float(locator.get("critical_threshold") or 95),
        details={"oldest_wait_seconds": backlog["oldest_wait_seconds"]},
    )


async def _probe_file_storage_capacity(
    locator: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    used = await asyncio.wait_for(storage.bucket_usage_bytes(), timeout_seconds)
    return _capacity_result(
        name="文件存储",
        capacity_kind="file_storage",
        used=used,
        capacity=int(locator.get("quota_bytes") or 0),
        warning_threshold=float(locator.get("warning_threshold") or 80),
        critical_threshold=float(locator.get("critical_threshold") or 90),
    )


async def _probe_vector_storage_capacity(locator: dict[str, Any]) -> dict[str, Any]:
    used = int(
        await DB.get().fetch_val(
            sa.text(
                "select coalesce(sum(pg_column_size(embedding)), 0) "
                "from t_document_chunk where embedding is not null"
            )
        )
        or 0
    )
    return _capacity_result(
        name="向量存储",
        capacity_kind="vector_storage",
        used=used,
        capacity=int(locator.get("quota_bytes") or 0),
        warning_threshold=float(locator.get("warning_threshold") or 80),
        critical_threshold=float(locator.get("critical_threshold") or 90),
    )


async def _probe_knowledge_qa(
    locator: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    kb_id = locator.get("kb_id")
    tenant_id = locator.get("tenant_id")
    user_id = locator.get("user_id")
    question = str(locator.get("fixed_question") or "").strip()
    if (
        not isinstance(kb_id, int)
        or isinstance(kb_id, bool)
        or kb_id <= 0
        or not isinstance(tenant_id, int)
        or isinstance(tenant_id, bool)
        or tenant_id <= 0
        or not user_id
        or not question
    ):
        raise ValueError("monitor probe isolation resources are not configured")
    knowledge_base = await knowledge_base_db.get(DB.get(), id=kb_id, status="active")
    if knowledge_base is None or knowledge_base.get("tenant_id") != tenant_id:
        raise ValueError("monitor probe knowledge base scope is invalid")
    qa_config = await qa_config_service.get_effective_config(
        DB.get(),
        kb_id,
        knowledge_base.get("system_prompt") or "",
    )
    result = await asyncio.wait_for(
        run(
            AgentTask(
                kb_id=kb_id,
                question=question,
                user_id=str(user_id),
                top_k=int(locator.get("top_k") or 3),
            ),
            AgentContext(
                tenant_id=tenant_id,
                user_id=str(user_id),
                kb_id=kb_id,
                index_version_id=knowledge_base.get("active_index_version_id"),
                knowledge_base_prompt=knowledge_base.get("system_prompt"),
                qa_config=qa_config,
                purpose="monitor_probe",
            ),
        ),
        timeout=timeout_seconds,
    )
    if result.status != "completed":
        raise RuntimeError("monitor knowledge probe did not complete")
    return {
        "status": "healthy",
        "hit_count": result.hit_count,
        "citation_count": len(result.citations),
    }


async def _execute_probe(locator: dict[str, Any]) -> dict[str, Any]:
    probe = str(locator.get("probe") or "")
    timeout_seconds = float(locator.get("timeout_seconds") or 5)
    if probe == "process_api":
        return {"status": "healthy"}
    if probe == "database":
        await asyncio.wait_for(DB.get().fetch_val(sa.text("select 1")), timeout_seconds)
        return {"status": "healthy"}
    if probe == "http_dependency":
        return await _probe_http_dependency(
            str(locator.get("config_group") or ""),
            timeout_seconds,
        )
    if probe == "vector_database":
        available = await asyncio.wait_for(
            DB.get().fetch_val(
                sa.text("select exists(select 1 from pg_extension where extname = 'vector')")
            ),
            timeout_seconds,
        )
        if not available:
            raise RuntimeError("vector extension unavailable")
        return {"status": "healthy"}
    if probe == "object_storage":
        available = await asyncio.wait_for(storage.health_check(), timeout_seconds)
        if not available:
            raise RuntimeError("object storage bucket unavailable")
        return {"status": "healthy"}
    if probe == "worker_status":
        return await _probe_worker_status(timeout_seconds)
    if probe == "task_backlog":
        return await _probe_task_backlog(timeout_seconds)
    if probe == "knowledge_qa":
        return await _probe_knowledge_qa(locator, timeout_seconds)
    if probe == "database_capacity":
        return await _probe_database_capacity(locator, timeout_seconds)
    if probe == "queue_capacity":
        return await _probe_queue_capacity(locator, timeout_seconds)
    if probe == "file_storage_capacity":
        return await _probe_file_storage_capacity(locator, timeout_seconds)
    if probe == "vector_storage_capacity":
        return await _probe_vector_storage_capacity(locator)
    raise ValueError(f"unsupported probe: {probe}")


def _is_due(
    locator: dict[str, Any],
    snapshot: dict[str, Any] | None,
) -> bool:
    checked_at = snapshot.get("checked_at") if snapshot else None
    if checked_at is None:
        return True
    interval = max(1, int(locator.get("interval_seconds") or 60))
    return checked_at + timedelta(seconds=interval) <= utils.utc_now()


async def _collect_target(target: dict[str, Any]) -> bool | None:
    locator = target.get("target_locator") or {}
    resource_type = str(locator.get("resource_type") or "probe")
    resource_code = str(locator.get("resource_code") or target["target_code"])
    existing = await snapshot_db.get(
        DB.get(),
        resource_type=resource_type,
        resource_code=resource_code,
        tenant_id=None,
    )
    if not _is_due(locator, existing):
        return None
    started_at = monotonic()
    expires_at = utils.utc_now() + timedelta(
        seconds=max(1, int(locator.get("interval_seconds") or 60)) * 3
    )
    try:
        result = await _execute_probe(locator)
        status = str(result.pop("status", "healthy"))
        latency_ms = int((monotonic() - started_at) * 1000)
        result["latency_ms"] = latency_ms
        await _upsert_snapshot(
            resource_type=resource_type,
            resource_code=resource_code,
            status=status,
            status_value=result,
            expires_at=expires_at,
        )
        await emit_gather_event(
            str(target["target_code"]),
            hook="periodic",
            source_code=resource_code,
            status=status,
            duration_ms=latency_ms,
            **result,
        )
        return status not in {"failed", "unavailable"}
    except Exception as exc:
        latency_ms = int((monotonic() - started_at) * 1000)
        await _upsert_snapshot(
            resource_type=resource_type,
            resource_code=resource_code,
            status="failed",
            status_value={"latency_ms": latency_ms},
            expires_at=expires_at,
            error_category=type(exc).__name__[:64],
        )
        await emit_gather_event(
            str(target["target_code"]),
            hook="periodic_error",
            source_code=resource_code,
            status="failed",
            duration_ms=latency_ms,
            latency_ms=latency_ms,
            error=exc,
        )
        LOG.opt(exception=exc).warning(
            "monitor probe failed target_code={}",
            target["target_code"],
        )
        return False


@check_db_connected
async def run_once() -> int:
    """采集入口；目标来自系统发布配置，业务页面不提供采集任务编辑。"""
    targets = await target_db.list(DB.get(), enabled=True)
    recovered_failure_count = await flush_gather_failures()
    probe_targets = [
        target
        for target in targets
        if target.get("target_type") == "probe"
        and (target.get("effective_at") is None or target["effective_at"] <= utils.utc_now())
    ]
    latest = {}
    for target in probe_targets:
        code = str(target["target_code"])
        current = latest.get(code)
        if current is None or int(target.get("version") or 0) > int(current.get("version") or 0):
            latest[code] = target
    success_count = 0
    failure_count = 0
    skipped_count = 0
    for target in latest.values():
        result = await _collect_target(target)
        if result is True:
            success_count += 1
        elif result is False:
            failure_count += 1
        else:
            skipped_count += 1
    target_count = len(latest)
    self_status = "healthy" if failure_count == 0 else "degraded"
    previous_self = await snapshot_db.get(
        DB.get(),
        resource_type="collector",
        resource_code="monitor-collector",
        tenant_id=None,
    )
    previous_values = (previous_self or {}).get("status_value") or {}
    now = utils.utc_now()
    last_success_at = (
        now.isoformat() if failure_count == 0 else previous_values.get("last_success_at")
    )
    last_failure_at = (
        now.isoformat() if failure_count > 0 else previous_values.get("last_failure_at")
    )
    consecutive_failure_count = (
        int(previous_values.get("consecutive_failure_count") or 0) + 1 if failure_count > 0 else 0
    )
    await _upsert_snapshot(
        resource_type="collector",
        resource_code="monitor-collector",
        status=self_status,
        status_value={
            "target_count": target_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "skipped_count": skipped_count,
            "last_success_at": last_success_at,
            "last_failure_at": last_failure_at,
            "consecutive_failure_count": consecutive_failure_count,
            "recovered_failure_count": recovered_failure_count,
        },
        expires_at=utils.utc_now() + timedelta(seconds=180),
    )
    await emit_gather_event(
        "collector.self",
        "collector_cycle_completed" if failure_count == 0 else "collector_cycle_failed",
        source_code="monitor-collector",
        status=self_status,
        target_count=target_count,
        success_count=success_count,
        failure_count=failure_count,
        skipped_count=skipped_count,
    )
    return target_count


async def run_forever(stop_event: asyncio.Event, interval_seconds: int = 60) -> None:
    await emit_gather_event(
        "worker.lifecycle",
        "worker_started",
        worker_name="monitoring_collect",
        source_code="monitoring_collect",
    )
    try:
        while not stop_event.is_set():
            try:
                await run_once()
                await emit_gather_event(
                    "worker.lifecycle",
                    "worker_heartbeat",
                    worker_name="monitoring_collect",
                    source_code="monitoring_collect",
                )
            except Exception as exc:
                LOG.opt(exception=exc).error("monitoring collect cycle failed")
                await emit_gather_event(
                    "worker.lifecycle",
                    "worker_failed",
                    worker_name="monitoring_collect",
                    source_code="monitoring_collect",
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
            worker_name="monitoring_collect",
            source_code="monitoring_collect",
        )
