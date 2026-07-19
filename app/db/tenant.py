from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import Tenant


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, Tenant, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, Tenant, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, Tenant, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        Tenant,
        order_by=[Tenant.c.created_at.desc(), Tenant.c.id.desc()],
        **kwargs,
    )


async def page(db, page: int = 1, page_size: int = 20, **kwargs: Any):
    return await db_api.page(
        db,
        Tenant,
        page=page,
        page_size=page_size,
        order_by=[Tenant.c.created_at.desc(), Tenant.c.id.desc()],
        **kwargs,
    )


__all__ = ("insert_", "update_", "get", "list", "page")
