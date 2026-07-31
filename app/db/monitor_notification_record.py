from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import MonitorNotificationRecord


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, MonitorNotificationRecord, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, MonitorNotificationRecord, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, MonitorNotificationRecord, values, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        MonitorNotificationRecord,
        order_by=[MonitorNotificationRecord.c.created_at.desc()],
        **kwargs,
    )


__all__ = ("insert_", "update_", "get", "list")
