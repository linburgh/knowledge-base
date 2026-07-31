from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import MonitorAlert


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, MonitorAlert, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, MonitorAlert, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, MonitorAlert, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db, MonitorAlert, order_by=[MonitorAlert.c.last_fired_at.desc()], **kwargs
    )


__all__ = ("insert_", "update_", "get", "list")
