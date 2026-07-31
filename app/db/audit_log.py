from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import AuditLog


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, AuditLog, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(db, AuditLog, order_by=[AuditLog.c.created_at.desc()], **kwargs)


__all__ = ("insert_", "list")
