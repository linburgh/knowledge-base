from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import MonitorAlertEvidence


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, MonitorAlertEvidence, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db, MonitorAlertEvidence, order_by=[MonitorAlertEvidence.c.created_at.asc()], **kwargs
    )


__all__ = ("insert_", "list")
