from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.models import KnowledgeBaseIndexVersion


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBaseIndexVersion, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, KnowledgeBaseIndexVersion, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, KnowledgeBaseIndexVersion, **kwargs)


async def list_(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        KnowledgeBaseIndexVersion,
        order_by=[
            KnowledgeBaseIndexVersion.c.created_at.desc(),
            KnowledgeBaseIndexVersion.c.id.desc(),
        ],
        **kwargs,
    )


async def next_generation(db, kb_id: int) -> int:
    query = sa.select(sa.func.count()).select_from(KnowledgeBaseIndexVersion).where(
        KnowledgeBaseIndexVersion.c.kb_id == kb_id
    )
    return int(await db.fetch_val(query)) + 1


__all__ = ("get", "insert_", "list_", "next_generation", "update_")
