from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import AuditLog


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, AuditLog, **kwargs)


__all__ = ("insert_",)
