from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.core.common.exception import BusiException
from app.core.common.auth import CurrentUser
from app.core.services.knowledge_base import document as document_service
from app.db import base as db_base


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeDatabase:
    def transaction(self):
        return FakeTransaction()


class IndexTaskActionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.database = FakeDatabase()
        self.user = CurrentUser(user_id="204", token="test-token")
        self.document = {"id": 23, "kb_id": 28}

    async def test_interrupt_accepts_pending_task(self):
        task = {"id": 91, "document_id": 23, "status": "pending", "version": 3}
        with (
            patch.object(db_base, "DATABASE", self.database),
            patch.object(
                document_service.access_service,
                "require_document_access",
                new=AsyncMock(return_value=self.document),
            ),
            patch.object(
                document_service.indexing_task_db,
                "get",
                new=AsyncMock(return_value=task),
            ),
            patch.object(
                document_service.ingestion_service,
                "interrupt_task",
                new=AsyncMock(return_value={**task, "status": "canceled"}),
            ) as interrupt,
        ):
            result = await document_service.interrupt_index(23, 91, 3, self.user)

        self.assertEqual(result["status"], "canceled")
        interrupt.assert_awaited_once_with(91, 3)

    async def test_interrupt_rejects_finished_task(self):
        task = {"id": 91, "document_id": 23, "status": "succeeded", "version": 4}
        with (
            patch.object(db_base, "DATABASE", self.database),
            patch.object(
                document_service.access_service,
                "require_document_access",
                new=AsyncMock(return_value=self.document),
            ),
            patch.object(
                document_service.indexing_task_db,
                "get",
                new=AsyncMock(return_value=task),
            ),
        ):
            with self.assertRaisesRegex(BusiException, "不可中断"):
                await document_service.interrupt_index(23, 91, 4, self.user)

    async def test_interrupt_rejects_stale_version(self):
        task = {"id": 91, "document_id": 23, "status": "running", "version": 3}
        with (
            patch.object(db_base, "DATABASE", self.database),
            patch.object(
                document_service.access_service,
                "require_document_access",
                new=AsyncMock(return_value=self.document),
            ),
            patch.object(
                document_service.indexing_task_db,
                "get",
                new=AsyncMock(return_value=task),
            ),
        ):
            with self.assertRaisesRegex(BusiException, "当前版本=3.*请求版本=2"):
                await document_service.interrupt_index(23, 91, 2, self.user)

    async def test_retry_creates_new_pending_task_and_keeps_source(self):
        source = {
            "id": 91,
            "document_id": 23,
            "kb_id": 28,
            "task_type": "index",
            "index_version_id": 7,
            "config_version_id": 8,
            "status": "interrupted",
            "version": 5,
        }
        new_task = {"id": 92, "document_id": 23, "status": "pending"}
        task_db = document_service.indexing_task_db
        with (
            patch.object(db_base, "DATABASE", self.database),
            patch.object(
                document_service.access_service,
                "require_document_access",
                new=AsyncMock(return_value=self.document),
            ),
            patch.object(
                task_db,
                "get",
                new=AsyncMock(side_effect=[source, {**source, "version": 6}, new_task]),
            ),
            patch.object(task_db, "list", new=AsyncMock(return_value=[])),
            patch.object(task_db, "update_", new=AsyncMock()),
            patch.object(task_db, "insert_", new=AsyncMock(return_value=92)) as insert,
            patch.object(document_service.document_db, "update_", new=AsyncMock()) as update,
        ):
            result = await document_service.retry_index(23, 91, 5, self.user)

        self.assertEqual(result, new_task)
        self.assertEqual(insert.await_args.kwargs["retry_of_task_id"], 91)
        self.assertEqual(update.await_args.args[1]["status"], "processing")

    async def test_retry_rejects_running_source(self):
        source = {"id": 91, "document_id": 23, "status": "running", "version": 1}
        with (
            patch.object(db_base, "DATABASE", self.database),
            patch.object(
                document_service.access_service,
                "require_document_access",
                new=AsyncMock(return_value=self.document),
            ),
            patch.object(
                document_service.indexing_task_db,
                "get",
                new=AsyncMock(return_value=source),
            ),
        ):
            with self.assertRaisesRegex(BusiException, "不可重试"):
                await document_service.retry_index(23, 91, 1, self.user)

    async def test_retry_rejects_stale_version(self):
        source = {
            "id": 91,
            "document_id": 23,
            "status": "canceled",
            "version": 7,
        }
        with (
            patch.object(db_base, "DATABASE", self.database),
            patch.object(
                document_service.access_service,
                "require_document_access",
                new=AsyncMock(return_value=self.document),
            ),
            patch.object(
                document_service.indexing_task_db,
                "get",
                new=AsyncMock(return_value=source),
            ),
        ):
            with self.assertRaisesRegex(BusiException, "当前版本=7.*请求版本=6"):
                await document_service.retry_index(23, 91, 6, self.user)


if __name__ == "__main__":
    unittest.main()
