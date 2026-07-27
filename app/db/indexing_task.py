from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import IndexingTask


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, IndexingTask, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    # 所有任务更新都采用版本递增，调用方可额外传入 version 做 CAS 校验。
    values = dict(values)
    values.setdefault("version", IndexingTask.c.version + 1)
    return await db_api.update_(db, IndexingTask, values, **kwargs)


async def delete_(db, **kwargs: Any) -> Any:
    return await db_api.delete_(db, IndexingTask, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, IndexingTask, **kwargs)


async def list(
    db,
    limit: int | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        IndexingTask,
        order_by=[IndexingTask.c.created_at.desc(), IndexingTask.c.id.desc()],
        limit=limit,
        **kwargs,
    )


async def count(db, **kwargs: Any) -> int:
    return await db_api.count(db, IndexingTask, **kwargs)


async def page(
    db,
    page: int = 1,
    page_size: int = 10,
    **kwargs: Any,
) -> dict[str, Any]:
    result = await db_api.page(
        db,
        IndexingTask,
        page=page,
        page_size=page_size,
        order_by=[IndexingTask.c.created_at.desc(), IndexingTask.c.id.desc()],
        **kwargs,
    )
    return {
        "items": result.rows,
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total,
    }


__all__ = ("insert_", "update_", "delete_", "get", "list", "count", "page")
