"""Inject audit failures and verify document/config transactions roll back."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.config import configure
from app.core.common.auth import CurrentUser
from app.core.services import document as document_service
from app.core.services import knowledge_base_qa_config as qa_service
from app.db import base
from app.db import document as document_db
from app.db import indexing_task as indexing_task_db
from app.db import knowledge_base_qa_config as qa_config_db
from app.db.models import Document
from app.schemas.document import DocumentCreateDto


async def main() -> None:
    configure("app")
    await base.setup()
    db = base.DATABASE
    document_id: int | None = None
    try:
        fixture_user = await db.fetch_one(
            "select id from t_user where username = :username",
            {"username": "e2e_eval_admin_20260726"},
        )
        if fixture_user is None:
            raise RuntimeError("P0 fixture admin user is missing")
        user_id = int(fixture_user["id"])
        async with db.transaction():
            document_id = int(
                await document_db.insert_(
                    db,
                    kb_id=34,
                    source_type="p0-rollback",
                    source_name="p0-rollback.md",
                    content_type="text/markdown",
                    object_path="tests/p0-rollback.md",
                    file_size=1,
                    content_hash="p0-rollback-hash",
                    created_by=str(user_id),
                    status="pending",
                )
            )
            await indexing_task_db.insert_(
                db,
                document_id=document_id,
                kb_id=34,
                task_type="index",
                status="pending",
            )

        with patch(
            "app.core.services.document.audit_service.record",
            new=AsyncMock(side_effect=RuntimeError("injected audit failure")),
        ):
            try:
                await document_service.remove(document_id)
            except RuntimeError:
                pass
            else:
                raise AssertionError("document remove should surface injected audit failure")
        document = await document_db.get(db, id=document_id)
        assert document is not None and document["status"] == "pending"
        print("PASS document delete audit failure rolls back document status")

        user = CurrentUser(user_id=str(user_id), tenant_id=3, token="p0-test")
        config = await qa_service.get_config(34, user)
        effective = config["effective"]
        await qa_service.save_draft(34, effective, user)
        draft = await qa_config_db.get_version(db, kb_id=34, status="draft")
        if draft is None:
            raise AssertionError("QA draft was not created")
        published_before = await qa_config_db.get_version(db, kb_id=34, status="published")
        with patch(
            "app.core.services.knowledge_base_qa_config.qa_config_db.insert_audit",
            new=AsyncMock(side_effect=RuntimeError("injected config audit failure")),
        ):
            try:
                await qa_service.publish(34, user, base_version=draft["version_no"])
            except RuntimeError:
                pass
            else:
                raise AssertionError("config publish should surface injected audit failure")
        draft_after = await qa_config_db.get_version(db, id=draft["id"])
        published_after = await qa_config_db.get_version(db, kb_id=34, status="published")
        assert draft_after is not None and draft_after["status"] == "draft"
        assert (published_before or {}).get("id") == (published_after or {}).get("id")
        print("PASS QA publish audit failure rolls back draft and published version")

    finally:
        if document_id is not None:
            async with db.transaction():
                await db.execute(
                    "delete from t_indexing_task where document_id = :document_id",
                    {"document_id": document_id},
                )
                await db.execute(
                    "delete from t_document_chunk where document_id = :document_id",
                    {"document_id": document_id},
                )
                await db.execute(
                    "delete from t_document where id = :document_id",
                    {"document_id": document_id},
                )
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
