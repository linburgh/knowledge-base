from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import MonitorNotificationPolicyChannel


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, MonitorNotificationPolicyChannel, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        MonitorNotificationPolicyChannel,
        order_by=[MonitorNotificationPolicyChannel.c.id.asc()],
        **kwargs,
    )


__all__ = ("insert_", "list")
