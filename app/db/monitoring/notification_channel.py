from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import MonitorNotificationChannel


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, MonitorNotificationChannel, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, MonitorNotificationChannel, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, MonitorNotificationChannel, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        MonitorNotificationChannel,
        order_by=[MonitorNotificationChannel.c.channel_code.asc()],
        **kwargs,
    )


__all__ = ("insert_", "update_", "get", "list")
