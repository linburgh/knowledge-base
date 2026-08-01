from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import MonitorEvent


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, MonitorEvent, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, MonitorEvent, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db, MonitorEvent, order_by=[MonitorEvent.c.occurred_at.desc()], **kwargs
    )


__all__ = ("insert_", "get", "list")
