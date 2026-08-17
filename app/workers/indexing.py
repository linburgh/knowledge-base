"""APScheduler-backed document indexing worker."""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import CONF
from app.core.common.log import LOG
from app.core.monitoring import emit_gather_event
from app.core.services.knowledge_base import ingestion
from app.db.knowledge_base import indexing_task as indexing_task_db
from app.db.api import check_db_connected
from app.db.base import DB

indexing_scheduler = AsyncIOScheduler()


@indexing_scheduler.scheduled_job(
    "interval",
    seconds=5,
    id="document-indexing-scheduler",
    max_instances=1,
    coalesce=True,
)
@check_db_connected
async def process_pending_tasks() -> None:
    """Claim and execute a small batch of pending indexing tasks."""
    await emit_gather_event(
        "worker.lifecycle",
        "worker_heartbeat",
        worker_name="indexing",
        source_code="indexing",
    )
    await ingestion.recover_stale_tasks()
    db = DB.get()
    for _ in range(max(1, int(CONF.default.indexing_scheduler_batch_size))):
        task = await indexing_task_db.claim_pending_task(db)
        if task is None:
            await emit_gather_event(
                "worker.lifecycle",
                "worker_idle",
                worker_name="indexing",
                source_code="indexing",
            )
            return
        await emit_gather_event(
            "worker.lifecycle",
            "worker_task_claimed",
            worker_name="indexing",
            source_code="indexing",
            task_id=task["id"],
        )
        await emit_gather_event(
            "document.indexing",
            "indexing_task_claimed",
            worker_name="indexing",
            task_id=task["id"],
            kb_id=task.get("kb_id"),
        )
        try:
            await ingestion.run_claimed_task(task["id"])
        except Exception as exc:
            LOG.exception(
                "document indexing scheduled task failed task_id={}",
                task["id"],
            )
            await emit_gather_event(
                "worker.lifecycle",
                "worker_failed",
                worker_name="indexing",
                source_code="indexing",
                task_id=task["id"],
                error=exc,
            )


async def recover_stale_tasks() -> int:
    """Recover stale tasks before the scheduler starts after a restart."""
    return await ingestion.recover_stale_tasks()


def start() -> None:
    """Start the in-process indexing scheduler."""
    if CONF.default.scheduler_enabled and not indexing_scheduler.running:
        indexing_scheduler.start()
        asyncio.get_running_loop().create_task(
            emit_gather_event(
                "worker.lifecycle",
                "worker_started",
                worker_name="indexing",
                source_code="indexing",
            )
        )


def stop() -> None:
    """Stop the in-process indexing scheduler."""
    if indexing_scheduler.running:
        indexing_scheduler.shutdown(wait=False)
        asyncio.get_running_loop().create_task(
            emit_gather_event(
                "worker.lifecycle",
                "worker_stopped",
                worker_name="indexing",
                source_code="indexing",
            )
        )


__all__ = (
    "indexing_scheduler",
    "process_pending_tasks",
    "recover_stale_tasks",
    "start",
    "stop",
)
