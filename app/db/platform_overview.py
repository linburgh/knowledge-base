from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from app.db.models import (
    AuditLog,
    Document,
    KnowledgeBase,
    Organization,
    Tenant,
    TenantMember,
    User,
)


async def metrics(db) -> dict[str, int]:
    user_scope = User.c.status != "deleted"
    tenant_scope = Tenant.c.status != "deleted"
    organization_scope = Organization.c.status != "deleted"
    knowledge_base_scope = KnowledgeBase.c.status != "deleted"

    queries = {
        "user_total": sa.select(sa.func.count()).select_from(User).where(user_scope),
        "active_user_total": sa.select(sa.func.count())
        .select_from(User)
        .where(User.c.status == "active"),
        "tenant_total": sa.select(sa.func.count()).select_from(Tenant).where(tenant_scope),
        "active_tenant_total": sa.select(sa.func.count())
        .select_from(Tenant)
        .where(Tenant.c.status == "active"),
        "organization_total": sa.select(sa.func.count())
        .select_from(Organization)
        .where(organization_scope),
        "knowledge_base_total": sa.select(sa.func.count())
        .select_from(KnowledgeBase)
        .where(knowledge_base_scope),
    }
    result: dict[str, int] = {}
    for name, query in queries.items():
        result[name] = int(await db.fetch_val(query) or 0)
    return result


async def user_trend(db, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
    created = sa.func.date_trunc("day", User.c.created_at).label("date")
    active = sa.func.date_trunc("day", User.c.last_login_at).label("date")
    created_rows = await db.fetch_all(
        sa.select(created, sa.func.count().label("total"))
        .where(
            User.c.status != "deleted",
            User.c.created_at >= start_at,
            User.c.created_at < end_at,
        )
        .group_by(created)
    )
    active_rows = await db.fetch_all(
        sa.select(active, sa.func.count(sa.distinct(User.c.id)).label("total"))
        .where(
            User.c.status != "deleted",
            User.c.last_login_at.is_not(None),
            User.c.last_login_at >= start_at,
            User.c.last_login_at < end_at,
        )
        .group_by(active)
    )
    created_map = {row["date"]: int(row["total"]) for row in created_rows}
    active_map = {row["date"]: int(row["total"]) for row in active_rows}
    return _merge_daily_values(start_at, end_at, created_map, active_map)


async def knowledge_base_trend(
    db,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    date_column = sa.func.date_trunc("day", KnowledgeBase.c.created_at).label("date")
    rows = await db.fetch_all(
        sa.select(date_column, sa.func.count().label("total"))
        .where(
            KnowledgeBase.c.status != "deleted",
            KnowledgeBase.c.created_at >= start_at,
            KnowledgeBase.c.created_at < end_at,
        )
        .group_by(date_column)
    )
    values = {row["date"]: int(row["total"]) for row in rows}
    return [
        {
            "date": point["date"],
            "new_knowledge_bases": point["new_knowledge_bases"],
        }
        for point in _merge_daily_values(start_at, end_at, {}, {}, values)
    ]


async def tenant_resources(db, limit: int = 5) -> list[dict[str, Any]]:
    user_count = sa.func.count(sa.distinct(TenantMember.c.user_id)).label("user_total")
    organization_count = sa.func.count(sa.distinct(Organization.c.id)).label(
        "organization_total"
    )
    knowledge_base_count = sa.func.count(sa.distinct(KnowledgeBase.c.id)).label(
        "knowledge_base_total"
    )
    query = (
        sa.select(
            Tenant.c.id.label("tenant_id"),
            Tenant.c.code.label("tenant_code"),
            Tenant.c.name.label("tenant_name"),
            user_count,
            organization_count,
            knowledge_base_count,
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
            Organization,
            sa.and_(
                Organization.c.tenant_id == Tenant.c.id,
                Organization.c.status != "deleted",
            ),
        )
        .outerjoin(
            KnowledgeBase,
            sa.and_(
                KnowledgeBase.c.tenant_id == Tenant.c.id,
                KnowledgeBase.c.status != "deleted",
            ),
        )
        .where(Tenant.c.status != "deleted")
        .group_by(Tenant.c.id, Tenant.c.code, Tenant.c.name)
        .order_by(
            user_count.desc(),
            organization_count.desc(),
            knowledge_base_count.desc(),
            Tenant.c.created_at.desc(),
            Tenant.c.id.desc(),
        )
        .limit(limit)
    )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def document_status(db) -> list[dict[str, Any]]:
    query = (
        sa.select(Document.c.status, sa.func.count().label("total"))
        .where(Document.c.status != "deleted")
        .group_by(Document.c.status)
        .order_by(Document.c.status)
    )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def recent_activities(db, limit: int = 5) -> list[dict[str, Any]]:
    query = (
        sa.select(
            AuditLog.c.id,
            AuditLog.c.actor_id,
            AuditLog.c.action,
            AuditLog.c.target_type,
            AuditLog.c.target_id,
            AuditLog.c.result,
            AuditLog.c.created_at,
        )
        .order_by(AuditLog.c.created_at.desc(), AuditLog.c.id.desc())
        .limit(limit)
    )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


def _merge_daily_values(
    start_at: datetime,
    end_at: datetime,
    new_users: dict[datetime, int],
    active_users: dict[datetime, int],
    new_knowledge_bases: dict[datetime, int] | None = None,
) -> list[dict[str, Any]]:
    values = []
    current = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
    last = end_at.replace(hour=0, minute=0, second=0, microsecond=0)
    while current < last:
        values.append(
            {
                "date": current,
                "new_users": new_users.get(current, 0),
                "active_users": active_users.get(current, 0),
                "new_knowledge_bases": (new_knowledge_bases or {}).get(current, 0),
            }
        )
        current = current + timedelta(days=1)
    return values


__all__ = (
    "document_status",
    "knowledge_base_trend",
    "metrics",
    "recent_activities",
    "tenant_resources",
    "user_trend",
)
