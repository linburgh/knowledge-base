from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import ConversationMessage


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, ConversationMessage, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, ConversationMessage, values, **kwargs)


async def delete_(db, **kwargs: Any) -> Any:
    return await db_api.delete_(db, ConversationMessage, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, ConversationMessage, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        ConversationMessage,
        order_by=[ConversationMessage.c.created_at.asc(), ConversationMessage.c.id.asc()],
        **kwargs,
    )


__all__ = ("insert_", "update_", "delete_", "get", "list")
