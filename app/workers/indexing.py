"""APScheduler-backed document indexing worker."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import CONF
from app.core.common.log import LOG
from app.core.services import ingestion
from app.db import indexing_task as indexing_task_db
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
    await ingestion.recover_stale_tasks()
    db = DB.get()
    for _ in range(max(1, int(CONF.default.indexing_scheduler_batch_size))):
        task = await indexing_task_db.claim_pending_task(db)
        if task is None:
            return
        try:
            await ingestion.run_claimed_task(task["id"])
        except Exception:
            LOG.exception(
                "document indexing scheduled task failed task_id={}",
                task["id"],
            )


async def recover_stale_tasks() -> int:
    """Recover stale tasks before the scheduler starts after a restart."""
    return await ingestion.recover_stale_tasks()


def start() -> None:
    """Start the in-process indexing scheduler."""
    if CONF.default.scheduler_enabled and not indexing_scheduler.running:
        indexing_scheduler.start()


def stop() -> None:
    """Stop the in-process indexing scheduler."""
    if indexing_scheduler.running:
        indexing_scheduler.shutdown(wait=False)


__all__ = (
    "indexing_scheduler",
    "process_pending_tasks",
    "recover_stale_tasks",
    "start",
    "stop",
)
