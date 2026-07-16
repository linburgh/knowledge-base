from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import KnowledgeBase


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBase, **kwargs)


async def update_(db, knowledge_base_id: int, values: dict[str, Any]) -> Any:
    return await db_api.update_(
        db,
        KnowledgeBase,
        values,
        id=knowledge_base_id,
    )


async def delete_(db, knowledge_base_id: int) -> Any:
    return await db_api.delete_(
        db,
        KnowledgeBase,
        id=knowledge_base_id,
    )


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, KnowledgeBase, **kwargs)


__all__ = ("insert_", "update_", "delete_", "get")
