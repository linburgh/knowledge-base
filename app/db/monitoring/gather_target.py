from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import MonitorGatherTarget


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, MonitorGatherTarget, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, MonitorGatherTarget, values, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db, MonitorGatherTarget, order_by=[MonitorGatherTarget.c.target_code.asc()], **kwargs
    )


__all__ = ("insert_", "update_", "list")
