from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import (
    KnowledgeBase,
    KnowledgeBaseOrganization,
    KnowledgeBaseUser,
    Tenant,
)


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


async def page_unbound(
    db,
    tenant_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
) -> PageRecord:
    conditions = [
        sa.or_(KnowledgeBase.c.tenant_id.is_(None), KnowledgeBase.c.tenant_id != tenant_id),
        KnowledgeBase.c.status != "deleted",
    ]
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            KnowledgeBase.c.name.ilike(pattern) | KnowledgeBase.c.description.ilike(pattern)
        )
    total_query = sa.select(sa.func.count()).select_from(KnowledgeBase).where(*conditions)
    query = _query({}).where(*conditions).order_by(KnowledgeBase.c.name.asc(), KnowledgeBase.c.id.asc())
    return PageRecord(
        rows=[dict(row) for row in await db.fetch_all(query.limit(page_size).offset((page - 1) * page_size))],
        total=int(await db.fetch_val(total_query)),
        page=page,
        page_size=page_size,
    )


async def bind_tenant(db, knowledge_base_ids: list[int], tenant_id: int) -> None:
    await db.execute(
        sa.update(KnowledgeBase)
        .where(KnowledgeBase.c.id.in_(knowledge_base_ids))
        .values(tenant_id=tenant_id, updated_at=sa.func.now())
    )


async def guest_page(
    db,
    tenant_id: int,
    user_id: int,
    organization_ids: list[int],
    page: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
) -> PageRecord:
    conditions = [
        KnowledgeBase.c.tenant_id == tenant_id,
        KnowledgeBase.c.status == "active",
    ]
    access_conditions = [
        sa.exists(
            sa.select(1)
            .select_from(KnowledgeBaseUser)
            .where(
                KnowledgeBaseUser.c.kb_id == KnowledgeBase.c.id,
                KnowledgeBaseUser.c.user_id == user_id,
            )
        )
    ]
    if organization_ids:
        access_conditions.append(
            sa.exists(
                sa.select(1)
                .select_from(KnowledgeBaseOrganization)
                .where(
                    KnowledgeBaseOrganization.c.kb_id == KnowledgeBase.c.id,
                    KnowledgeBaseOrganization.c.organization_id.in_(organization_ids),
                )
            )
        )
    conditions.append(sa.or_(*access_conditions))
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            sa.or_(
                KnowledgeBase.c.name.ilike(pattern),
                KnowledgeBase.c.description.ilike(pattern),
            )
        )

    query = sa.select(
        KnowledgeBase.c.id,
        KnowledgeBase.c.name,
        KnowledgeBase.c.description,
        KnowledgeBase.c.status,
    ).where(*conditions).order_by(
        KnowledgeBase.c.updated_at.desc(), KnowledgeBase.c.id.desc()
    )
    count_query = sa.select(sa.func.count()).select_from(KnowledgeBase).where(*conditions)
    record = PageRecord(
        rows=[],
        total=int(await db.fetch_val(count_query)),
        page=page,
        page_size=page_size,
    )
    rows = await db.fetch_all(
        query.limit(page_size).offset((page - 1) * page_size)
    )
    record.rows = [dict(row) for row in rows]
    return record


async def guest_get(
    db,
    tenant_id: int,
    user_id: int,
    organization_ids: list[int],
    knowledge_base_id: int,
) -> dict[str, Any] | None:
    conditions = [
        KnowledgeBase.c.id == knowledge_base_id,
        KnowledgeBase.c.tenant_id == tenant_id,
        KnowledgeBase.c.status == "active",
    ]
    access_conditions = [
        sa.exists(
            sa.select(1)
            .select_from(KnowledgeBaseUser)
            .where(
                KnowledgeBaseUser.c.kb_id == KnowledgeBase.c.id,
                KnowledgeBaseUser.c.user_id == user_id,
            )
        )
    ]
    if organization_ids:
        access_conditions.append(
            sa.exists(
                sa.select(1)
                .select_from(KnowledgeBaseOrganization)
                .where(
                    KnowledgeBaseOrganization.c.kb_id == KnowledgeBase.c.id,
                    KnowledgeBaseOrganization.c.organization_id.in_(organization_ids),
                )
            )
        )
    conditions.append(
        sa.or_(*access_conditions)
    )
    row = await db.fetch_one(
        sa.select(
            KnowledgeBase.c.id,
            KnowledgeBase.c.name,
            KnowledgeBase.c.description,
            KnowledgeBase.c.status,
        ).where(*conditions)
    )
    return dict(row) if row else None


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


__all__ = (
    "insert_",
    "update_",
    "delete_",
    "get",
    "count",
    "list",
    "page",
    "guest_page",
    "guest_get",
)
