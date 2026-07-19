from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.models import KnowledgeBase, Tenant, TenantMember


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, Tenant, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, Tenant, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, Tenant, **kwargs)


async def get_with_stats(db, tenant_id: int) -> dict[str, Any] | None:
    query = (
        sa.select(
            Tenant,
            sa.func.count(sa.distinct(TenantMember.c.user_id)).label("member_count"),
            sa.func.count(sa.distinct(KnowledgeBase.c.id)).label("knowledge_base_count"),
        )
        .select_from(Tenant)
        .outerjoin(
            TenantMember,
            sa.and_(
                TenantMember.c.tenant_id == Tenant.c.id,
                TenantMember.c.status == "active",
            ),
        )
        .outerjoin(
            KnowledgeBase,
            sa.and_(
                KnowledgeBase.c.tenant_id == Tenant.c.id,
                KnowledgeBase.c.status != "deleted",
            ),
        )
        .where(Tenant.c.id == tenant_id)
        .group_by(*Tenant.c)
    )
    row = await db.fetch_one(query)
    return dict(row) if row else None


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


__all__ = ("insert_", "update_", "get", "get_with_stats", "list", "page")
