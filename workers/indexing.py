"""持久化文档索引 Worker。"""

from __future__ import annotations

import asyncio

from app.config import CONF
from app.core.common.log import LOG
from app.core.services import ingestion
from app.db import indexing_task as indexing_task_db
from app.db.api import check_db_connected
from app.db.base import DB


@check_db_connected
async def run_pending_once() -> bool:
    db = DB.get()
    await ingestion.recover_stale_tasks()
    tasks = await indexing_task_db.list(db, status="pending", limit=1)
    if not tasks:
        return False
    task = tasks[0]
    try:
        await ingestion.run_task(task["id"])
    except Exception:
        LOG.exception("document indexing task failed task_id={}", task["id"])
    return True


async def run_forever(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            processed = await run_pending_once()
        except Exception:
            LOG.exception("document indexing worker iteration failed")
            processed = False
        if processed:
            continue
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=max(1, int(CONF.default.indexing_worker_poll_seconds)),
            )
        except TimeoutError:
            continue


__all__ = ("run_forever", "run_pending_once")
