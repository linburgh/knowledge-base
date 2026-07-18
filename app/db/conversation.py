from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import Conversation


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, Conversation, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, Conversation, values, **kwargs)


async def delete_(db, **kwargs: Any) -> Any:
    return await db_api.delete_(db, Conversation, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, Conversation, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        Conversation,
        order_by=[Conversation.c.updated_at.desc(), Conversation.c.id.desc()],
        **kwargs,
    )


__all__ = ("insert_", "update_", "delete_", "get", "list")
