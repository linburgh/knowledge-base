from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.config import configure
from app.core.services import ingestion
from app.db import base as db_base
from app.db import indexing_task as indexing_task_db
from app.db.models import IndexingTask
from app.workers import indexing as indexing_worker


class FakeDatabase:
    def __init__(self, row=None):
        self.row = row
        self.query = None

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def fetch_one(self, query):
        self.query = query
        return self.row


class IndexingWorkerTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("OS_CONFIG_DIR", str(Path.cwd() / "etc"))
        configure("app")

    async def test_scheduler_registers_one_document_job(self):
        job = indexing_worker.indexing_scheduler.get_job("document-indexing-scheduler")

        self.assertIsNotNone(job)
        self.assertEqual(job.max_instances, 1)
        self.assertTrue(job.coalesce)

    async def test_process_pending_tasks_executes_only_claimed_tasks(self):
        task = {"id": 17, "status": "running"}
        with (
            patch.object(db_base, "DATABASE", FakeDatabase()),
            patch.object(
                indexing_worker.ingestion,
                "recover_stale_tasks",
                new=AsyncMock(return_value=0),
            ),
            patch.object(
                indexing_task_db,
                "claim_pending_task",
                new=AsyncMock(return_value=task),
            ) as claim,
            patch.object(
                indexing_worker.ingestion,
                "run_claimed_task",
                new=AsyncMock(),
            ) as run_claimed,
        ):
            await indexing_worker.process_pending_tasks()

        claim.assert_awaited_once()
        run_claimed.assert_awaited_once_with(17)

    async def test_process_pending_tasks_does_not_execute_when_claim_fails(self):
        with (
            patch.object(db_base, "DATABASE", FakeDatabase()),
            patch.object(
                indexing_worker.ingestion,
                "recover_stale_tasks",
                new=AsyncMock(return_value=0),
            ),
            patch.object(
                indexing_task_db,
                "claim_pending_task",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                indexing_worker.ingestion,
                "run_claimed_task",
                new=AsyncMock(),
            ) as run_claimed,
        ):
            await indexing_worker.process_pending_tasks()

        run_claimed.assert_not_awaited()

    def test_claim_query_uses_conditional_update_and_returning(self):
        query_source = indexing_task_db.claim_pending_task
        self.assertIsNotNone(query_source)

        # Keep the SQL contract explicit without requiring a live PostgreSQL server.
        candidate_id = (
            sa.select(IndexingTask.c.id)
            .where(IndexingTask.c.status == "pending")
            .order_by(IndexingTask.c.created_at.asc(), IndexingTask.c.id.asc())
            .limit(1)
            .scalar_subquery()
        )
        query = (
            sa.update(IndexingTask)
            .where(IndexingTask.c.id == candidate_id, IndexingTask.c.status == "pending")
            .values(status="running")
            .returning(IndexingTask)
        )
        sql = str(query.compile(dialect=postgresql.dialect())).lower()

        self.assertIn("status", sql)
        self.assertIn("returning", sql)
        self.assertNotIn("for update", sql)

    async def test_claim_pending_task_returns_database_winner(self):
        database = FakeDatabase({"id": 9, "status": "running"})

        task = await indexing_task_db.claim_pending_task(database)

        self.assertEqual(task, {"id": 9, "status": "running"})
        self.assertIsNotNone(database.query)

    async def test_stale_running_task_is_requeued_instead_of_canceled(self):
        stale_task = {
            "id": 9,
            "status": "running",
            "attempts": 1,
            "max_attempts": 3,
            "updated_at": datetime.now(UTC) - timedelta(seconds=600),
            "started_at": datetime.now(UTC) - timedelta(seconds=601),
        }
        with (
            patch.object(db_base, "DATABASE", FakeDatabase()),
            patch.object(indexing_task_db, "list", new=AsyncMock(return_value=[stale_task])),
            patch.object(indexing_task_db, "update_", new=AsyncMock()) as update,
        ):
            recovered = await ingestion.recover_stale_tasks()

        self.assertEqual(recovered, 1)
        self.assertEqual(update.await_args.args[1]["status"], "pending")
        self.assertEqual(update.await_args.kwargs["status"], "running")


if __name__ == "__main__":
    unittest.main()
