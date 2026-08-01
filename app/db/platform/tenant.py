from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import KnowledgeBase, Organization, Tenant, TenantMember, User


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, Tenant, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, Tenant, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, Tenant, **kwargs)


async def get_with_stats(db, tenant_id: int) -> dict[str, Any] | None:
    organization_count = (
        sa.select(sa.func.count(sa.distinct(Organization.c.id)))
        .where(
            Organization.c.tenant_id == Tenant.c.id,
            Organization.c.status != "deleted",
        )
        .scalar_subquery()
    )
    query = (
        sa.select(
            Tenant,
            sa.func.count(sa.distinct(TenantMember.c.user_id)).label("member_count"),
            sa.func.count(sa.distinct(KnowledgeBase.c.id)).label("knowledge_base_count"),
            organization_count.label("organization_count"),
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
    query = _stats_query(**kwargs).order_by(Tenant.c.created_at.desc(), Tenant.c.id.desc())
    for condition in _tenant_filters(kwargs):
        query = query.where(condition)
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def page(db, page: int = 1, page_size: int = 20, **kwargs: Any):
    query = _stats_query(**kwargs).order_by(Tenant.c.created_at.desc(), Tenant.c.id.desc())
    total_query = sa.select(sa.func.count()).select_from(Tenant)
    filters = _tenant_filters(kwargs)
    for condition in filters:
        query = query.where(condition)
        total_query = total_query.where(condition)
    record = PageRecord(
        rows=[],
        total=int(await db.fetch_val(total_query)),
        page=page,
        page_size=page_size,
    )
    rows = await db.fetch_all(query.limit(page_size).offset((page - 1) * page_size))
    record.rows = [dict(row) for row in rows]
    return record


def _tenant_filters(kwargs: dict[str, Any]) -> list[Any]:
    filters: list[Any] = []
    for field in ("code", "status"):
        value = kwargs.get(field)
        if value is not None:
            filters.append(getattr(Tenant.c, field) == value)
    if kwargs.get("name") is not None:
        filters.append(Tenant.c.name.ilike(f"%{kwargs['name']}%"))
    status_ne = kwargs.get("status__ne")
    if status_ne is not None:
        filters.append(Tenant.c.status != status_ne)
    return filters


def _stats_query(**kwargs: Any):
    member_count = (
        sa.select(sa.func.count(sa.distinct(TenantMember.c.user_id)))
        .where(TenantMember.c.tenant_id == Tenant.c.id, TenantMember.c.status == "active")
        .scalar_subquery()
    )
    knowledge_base_count = (
        sa.select(sa.func.count(sa.distinct(KnowledgeBase.c.id)))
        .where(
            KnowledgeBase.c.tenant_id == Tenant.c.id,
            KnowledgeBase.c.status != "deleted",
        )
        .scalar_subquery()
    )
    organization_count = (
        sa.select(sa.func.count(sa.distinct(Organization.c.id)))
        .where(
            Organization.c.tenant_id == Tenant.c.id,
            Organization.c.status != "deleted",
        )
        .scalar_subquery()
    )
    tenant_admin = (
        sa.select(sa.func.string_agg(User.c.display_name, sa.literal(", ")))
        .select_from(TenantMember.join(User, User.c.id == TenantMember.c.user_id))
        .where(
            TenantMember.c.tenant_id == Tenant.c.id,
            TenantMember.c.status == "active",
            TenantMember.c.role_code == "tenant_admin",
        )
        .scalar_subquery()
    )
    return sa.select(
        Tenant,
        member_count.label("member_count"),
        knowledge_base_count.label("knowledge_base_count"),
        organization_count.label("organization_count"),
        tenant_admin.label("tenant_admin"),
    )


__all__ = ("insert_", "update_", "get", "get_with_stats", "list", "page")
