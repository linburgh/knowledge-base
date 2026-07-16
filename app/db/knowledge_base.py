from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import KnowledgeBase


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBase, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, KnowledgeBase, values, **kwargs)


async def delete_(db, **kwargs: Any) -> Any:
    return await db_api.delete_(db, KnowledgeBase, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, KnowledgeBase, **kwargs)


async def count(db, **kwargs: Any) -> int:
    return await db_api.count(db, KnowledgeBase, **kwargs)


async def list(
    db,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        KnowledgeBase,
        order_by=[KnowledgeBase.c.created_at.desc(), KnowledgeBase.c.id.desc()],
        **kwargs,
    )


async def page(
    db,
    page: int = 1,
    page_size: int = 20,
    **kwargs: Any,
):
    return await db_api.page(
        db,
        KnowledgeBase,
        page=page,
        page_size=page_size,
        order_by=[KnowledgeBase.c.created_at.desc(), KnowledgeBase.c.id.desc()],
        **kwargs,
    )


__all__ = ("insert_", "update_", "delete_", "get", "count", "list", "page")
