from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import DocumentChunk


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, DocumentChunk, **kwargs)


async def batch_insert(db, rows: list[dict[str, Any]]) -> None:
    await db_api.batch_insert(db, DocumentChunk, rows)


async def delete_(db, **kwargs: Any) -> Any:
    return await db_api.delete_(db, DocumentChunk, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        DocumentChunk,
        order_by=[DocumentChunk.c.chunk_index.asc(), DocumentChunk.c.id.asc()],
        **kwargs,
    )


__all__ = ("insert_", "batch_insert", "delete_", "list")
