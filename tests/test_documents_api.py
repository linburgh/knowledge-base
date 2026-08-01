from __future__ import annotations

import pytest

from app.core.services.knowledge_base import document


class _Upload:
    filename = "采集链路验证.md"
    content_type = "text/markdown"


@pytest.mark.asyncio
async def test_upload_does_not_create_a_second_indexing_task(monkeypatch):
    async def upload_file(*_):
        return "documents/28/hash.md", 32, "hash"

    async def add(dto):
        assert dto.kb_id == 28
        return {"id": 35, "kb_id": 28}

    async def duplicate_task(*_):
        raise AssertionError("add 已在事务内创建索引任务，upload 不得重复创建")

    monkeypatch.setattr(document, "upload_file", upload_file)
    monkeypatch.setattr(document, "add", add)
    monkeypatch.setattr(document.ingestion_service, "create_task", duplicate_task)

    result = await document.upload.__wrapped__(_Upload(), 28, "204", parser="markdown")

    assert result == {"id": 35, "kb_id": 28}
