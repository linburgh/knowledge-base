from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from app.db.models import (
    AuditLog,
    Document,
    EvaluationRun,
    EvaluationTask,
    KnowledgeBase,
    Organization,
    OrganizationMember,
    Tenant,
    TenantMember,
    User,
)


NON_BUSINESS_ACTIVITY_ACTIONS = (
    "login",
    "logout",
    "refresh_token",
    "select_tenant",
)


async def metrics(db, tenant_id: int | None = None) -> dict[str, int]:
    user_scope = User.c.status != "deleted"
    tenant_scope = Tenant.c.status != "deleted"
    organization_scope = Organization.c.status != "deleted"
    knowledge_base_scope = KnowledgeBase.c.status != "deleted"

    user_query = sa.select(sa.func.count(sa.distinct(User.c.id))).select_from(User)
    active_user_query = sa.select(sa.func.count(sa.distinct(User.c.id))).select_from(User)
    tenant_query = sa.select(sa.func.count()).select_from(Tenant)
    active_tenant_query = sa.select(sa.func.count()).select_from(Tenant)
    organization_query = sa.select(sa.func.count()).select_from(Organization)
    knowledge_base_query = sa.select(sa.func.count()).select_from(KnowledgeBase)
    if tenant_id is not None:
        user_from = User.join(
            TenantMember,
            sa.and_(
                TenantMember.c.user_id == User.c.id,
                TenantMember.c.tenant_id == tenant_id,
                TenantMember.c.status == "active",
            ),
        )
        user_query = sa.select(sa.func.count(sa.distinct(User.c.id))).select_from(user_from)
        active_user_query = sa.select(sa.func.count(sa.distinct(User.c.id))).select_from(user_from)
        tenant_query = tenant_query.where(Tenant.c.id == tenant_id)
        active_tenant_query = active_tenant_query.where(Tenant.c.id == tenant_id)
        organization_query = organization_query.where(Organization.c.tenant_id == tenant_id)
        knowledge_base_query = knowledge_base_query.where(KnowledgeBase.c.tenant_id == tenant_id)
    queries = {
        "user_total": user_query.where(user_scope),
        "active_user_total": active_user_query.where(User.c.status == "active"),
        "tenant_total": tenant_query.where(tenant_scope),
        "active_tenant_total": active_tenant_query.where(Tenant.c.status == "active"),
        "organization_total": organization_query.where(organization_scope),
        "knowledge_base_total": knowledge_base_query.where(knowledge_base_scope),
    }
    result: dict[str, int] = {}
    for name, query in queries.items():
        result[name] = int(await db.fetch_val(query) or 0)
    return result


async def user_trend(
    db, start_at: datetime, end_at: datetime, tenant_id: int | None = None
) -> list[dict[str, Any]]:
    created = sa.func.date_trunc("day", User.c.created_at).label("date")
    active = sa.func.date_trunc("day", User.c.last_login_at).label("date")
    created_query = sa.select(created, sa.func.count(sa.distinct(User.c.id)).label("total"))
    active_query = sa.select(active, sa.func.count(sa.distinct(User.c.id)).label("total"))
    if tenant_id is not None:
        created_query = created_query.select_from(
            User.join(
                TenantMember,
                sa.and_(
                    TenantMember.c.user_id == User.c.id,
                    TenantMember.c.tenant_id == tenant_id,
                    TenantMember.c.status == "active",
                ),
            )
        )
        active_query = active_query.select_from(
            User.join(
                TenantMember,
                sa.and_(
                    TenantMember.c.user_id == User.c.id,
                    TenantMember.c.tenant_id == tenant_id,
                    TenantMember.c.status == "active",
                ),
            )
        )
    created_rows = await db.fetch_all(
        created_query
        .where(
            User.c.status != "deleted",
            User.c.created_at >= start_at,
            User.c.created_at < end_at,
        )
        .group_by(created)
    )
    active_rows = await db.fetch_all(
        active_query
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
    tenant_id: int | None = None,
) -> list[dict[str, Any]]:
    date_column = sa.func.date_trunc("day", KnowledgeBase.c.created_at).label("date")
    query = sa.select(date_column, sa.func.count().label("total")).select_from(KnowledgeBase)
    if tenant_id is not None:
        query = query.where(KnowledgeBase.c.tenant_id == tenant_id)
    rows = await db.fetch_all(
        query
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


async def tenant_resources(
    db, limit: int = 5, tenant_id: int | None = None
) -> list[dict[str, Any]]:
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
    if tenant_id is not None:
        query = query.where(Tenant.c.id == tenant_id)
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def document_status(db, tenant_id: int | None = None) -> list[dict[str, Any]]:
    query = sa.select(Document.c.status, sa.func.count().label("total")).select_from(
        Document.join(KnowledgeBase, Document.c.kb_id == KnowledgeBase.c.id)
    )
    if tenant_id is not None:
        query = query.where(KnowledgeBase.c.tenant_id == tenant_id)
    query = (
        query.where(Document.c.status != "deleted")
        .group_by(Document.c.status)
        .order_by(Document.c.status)
    )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def recent_activities(
    db, limit: int = 5, tenant_id: int | None = None
) -> list[dict[str, Any]]:
    target_scope = None
    if tenant_id is not None:
        target_id = AuditLog.c.target_id
        target_scope = sa.or_(
            sa.exists(
                sa.select(1)
                .select_from(Tenant)
                .where(
                    AuditLog.c.target_type == "tenant",
                    target_id == sa.cast(Tenant.c.id, sa.String),
                    Tenant.c.id == tenant_id,
                )
            ),
            sa.exists(
                sa.select(1)
                .select_from(Organization)
                .where(
                    AuditLog.c.target_type == "organization",
                    target_id == sa.cast(Organization.c.id, sa.String),
                    Organization.c.tenant_id == tenant_id,
                )
            ),
            sa.exists(
                sa.select(1)
                .select_from(
                    OrganizationMember.join(
                        Organization,
                        OrganizationMember.c.organization_id == Organization.c.id,
                    )
                )
                .where(
                    AuditLog.c.target_type == "organization_member",
                    target_id == sa.cast(OrganizationMember.c.id, sa.String),
                    Organization.c.tenant_id == tenant_id,
                )
            ),
            sa.exists(
                sa.select(1)
                .select_from(KnowledgeBase)
                .where(
                    AuditLog.c.target_type == "knowledge_base",
                    target_id == sa.cast(KnowledgeBase.c.id, sa.String),
                    KnowledgeBase.c.tenant_id == tenant_id,
                )
            ),
            sa.exists(
                sa.select(1)
                .select_from(
                    Document.join(
                        KnowledgeBase,
                        Document.c.kb_id == KnowledgeBase.c.id,
                    )
                )
                .where(
                    AuditLog.c.target_type == "document",
                    target_id == sa.cast(Document.c.id, sa.String),
                    KnowledgeBase.c.tenant_id == tenant_id,
                )
            ),
            sa.exists(
                sa.select(1)
                .select_from(EvaluationTask)
                .where(
                    AuditLog.c.target_type == "evaluation_task",
                    target_id == sa.cast(EvaluationTask.c.id, sa.String),
                    EvaluationTask.c.tenant_id == tenant_id,
                )
            ),
            sa.exists(
                sa.select(1)
                .select_from(
                    EvaluationRun.join(
                        EvaluationTask,
                        EvaluationRun.c.task_id == EvaluationTask.c.id,
                    )
                )
                .where(
                    AuditLog.c.target_type == "evaluation_run",
                    target_id == sa.cast(EvaluationRun.c.id, sa.String),
                    EvaluationTask.c.tenant_id == tenant_id,
                )
            ),
            sa.exists(
                sa.select(1)
                .select_from(TenantMember)
                .where(
                    AuditLog.c.target_type == "tenant_member",
                    target_id == sa.cast(TenantMember.c.id, sa.String),
                    TenantMember.c.tenant_id == tenant_id,
                )
            ),
            sa.exists(
                sa.select(1)
                .select_from(TenantMember)
                .where(
                    AuditLog.c.target_type == "user",
                    target_id == sa.cast(TenantMember.c.user_id, sa.String),
                    TenantMember.c.tenant_id == tenant_id,
                    TenantMember.c.status != "left",
                )
            ),
        )
    query = (
        sa.select(
            AuditLog.c.id,
            AuditLog.c.actor_id,
            AuditLog.c.action,
            AuditLog.c.action_cn,
            AuditLog.c.target_type,
            AuditLog.c.target_id,
            AuditLog.c.result,
            AuditLog.c.created_at,
        )
        .where(AuditLog.c.action.not_in(NON_BUSINESS_ACTIVITY_ACTIONS))
        .order_by(AuditLog.c.created_at.desc(), AuditLog.c.id.desc())
        .limit(limit)
    )
    if tenant_id is not None:
        query = query.where(target_scope)
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
