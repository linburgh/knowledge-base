from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import KnowledgeBase, Tenant


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBase, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, KnowledgeBase, values, **kwargs)


async def delete_(db, **kwargs: Any) -> Any:
    return await db_api.delete_(db, KnowledgeBase, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, KnowledgeBase, **kwargs)


async def count(db, **kwargs: Any) -> int:
    return await db_api.count(db, KnowledgeBase, **kwargs)


async def list(
    db,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    query = _query(kwargs).order_by(KnowledgeBase.c.created_at.desc(), KnowledgeBase.c.id.desc())
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def page(
    db,
    page: int = 1,
    page_size: int = 20,
    **kwargs: Any,
):
    query = _query(kwargs).order_by(KnowledgeBase.c.created_at.desc(), KnowledgeBase.c.id.desc())
    count_query = sa.select(sa.func.count()).select_from(KnowledgeBase)
    conditions = _conditions(kwargs)
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)
    record = PageRecord(
        rows=[],
        total=int(await db.fetch_val(count_query)),
        page=page,
        page_size=page_size,
    )
    rows = await db.fetch_all(query.limit(page_size).offset((page - 1) * page_size))
    record.rows = [dict(row) for row in rows]
    return record


def _conditions(kwargs: dict[str, Any]) -> list[Any]:
    conditions: list[Any] = []
    for key, value in kwargs.items():
        if value is None:
            continue
        if key == "name":
            conditions.append(KnowledgeBase.c.name.ilike(f"%{value}%"))
        elif key.endswith("__ne"):
            conditions.append(getattr(KnowledgeBase.c, key[:-4]) != value)
        else:
            conditions.append(getattr(KnowledgeBase.c, key) == value)
    return conditions


def _query(kwargs: dict[str, Any]):
    query = sa.select(
        KnowledgeBase,
        Tenant.c.name.label("tenant_name"),
    ).select_from(
        KnowledgeBase.outerjoin(
            Tenant,
            Tenant.c.id == KnowledgeBase.c.tenant_id,
        )
    )
    conditions = _conditions(kwargs)
    return query.where(*conditions) if conditions else query


__all__ = ("insert_", "update_", "delete_", "get", "count", "list", "page")
