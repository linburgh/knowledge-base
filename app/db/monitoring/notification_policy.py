from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import MonitorNotificationPolicy


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, MonitorNotificationPolicy, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, MonitorNotificationPolicy, values, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        MonitorNotificationPolicy,
        order_by=[MonitorNotificationPolicy.c.policy_name.asc()],
        **kwargs,
    )


__all__ = ("insert_", "update_", "list")
