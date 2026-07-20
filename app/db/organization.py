from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import Organization, OrganizationMember, Tenant, TenantMember, User


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, Organization, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, Organization, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, Organization, **kwargs)


async def list(
    db,
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    leader_user = User.alias("organization_leader_user")
    member_count = sa.func.count(
        sa.distinct(OrganizationMember.c.id)
    ).filter(OrganizationMember.c.status == "active")
    query = (
        sa.select(
            Organization,
            Tenant.c.name.label("tenant_name"),
            leader_user.c.display_name.label("leader_name"),
            leader_user.c.username.label("leader_username"),
            member_count.label("member_count"),
        )
        .select_from(Organization)
        .join(Tenant, Tenant.c.id == Organization.c.tenant_id)
        .outerjoin(leader_user, leader_user.c.id == Organization.c.leader_user_id)
        .outerjoin(
            OrganizationMember,
            OrganizationMember.c.organization_id == Organization.c.id,
        )
        .where(Tenant.c.status != "deleted")
        .group_by(
            *Organization.c,
            Tenant.c.name,
            leader_user.c.display_name,
            leader_user.c.username,
        )
        .order_by(
            Organization.c.tenant_id.asc(),
            Organization.c.created_at.asc(),
            Organization.c.id.asc(),
        )
    )
    if tenant_id is not None:
        query = query.where(Organization.c.tenant_id == tenant_id)
    if status is None:
        query = query.where(Organization.c.status != "deleted")
    else:
        query = query.where(Organization.c.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            Organization.c.name.ilike(pattern) | Organization.c.code.ilike(pattern)
        )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def page(
    db,
    page: int = 1,
    page_size: int = 20,
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
) -> PageRecord:
    query = sa.select(Organization).select_from(Organization)
    total_query = sa.select(sa.func.count()).select_from(Organization)
    tenant_join = Tenant.c.id == Organization.c.tenant_id
    query = query.join(Tenant, tenant_join)
    total_query = total_query.join(Tenant, tenant_join)
    conditions = [Tenant.c.status != "deleted"]
    if tenant_id is not None:
        conditions.append(Organization.c.tenant_id == tenant_id)
    if status is None:
        conditions.append(Organization.c.status != "deleted")
    else:
        conditions.append(Organization.c.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            Organization.c.name.ilike(pattern) | Organization.c.code.ilike(pattern)
        )
    query = query.where(*conditions).order_by(
        Organization.c.tenant_id.asc(),
        Organization.c.created_at.asc(),
        Organization.c.id.asc(),
    )
    total_query = total_query.where(*conditions)
    record = PageRecord(
        rows=[],
        total=int(await db.fetch_val(total_query)),
        page=page,
        page_size=page_size,
    )
    rows = await db.fetch_all(query.limit(page_size).offset((page - 1) * page_size))
    record.rows = [dict(row) for row in rows]
    return record


async def count_children(db, tenant_id: int, parent_id: int, include_deleted: bool = False) -> int:
    query = sa.select(sa.func.count()).select_from(Organization).where(
        Organization.c.tenant_id == tenant_id,
        Organization.c.parent_id == parent_id,
    )
    if not include_deleted:
        query = query.where(Organization.c.status != "deleted")
    return int(await db.fetch_val(query))


async def insert_member(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, OrganizationMember, **kwargs)


async def update_member(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, OrganizationMember, values, **kwargs)


async def get_member(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, OrganizationMember, **kwargs)


async def get_tenant_member(
    db,
    tenant_id: int,
    user_id: int,
    status: str = "active",
) -> dict[str, Any] | None:
    return await db_api.get(
        db,
        TenantMember,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status,
    )


def _member_query(
    organization_id: int,
    keyword: str | None = None,
    status: str | None = None,
):
    query = (
        sa.select(
            OrganizationMember,
            User.c.username,
            User.c.email,
            User.c.display_name,
        )
        .select_from(OrganizationMember)
        .join(User, User.c.id == OrganizationMember.c.user_id)
        .where(OrganizationMember.c.organization_id == organization_id)
        .order_by(OrganizationMember.c.created_at.desc(), OrganizationMember.c.id.desc())
    )
    if status is None:
        query = query.where(OrganizationMember.c.status != "left")
    else:
        query = query.where(OrganizationMember.c.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            User.c.username.ilike(pattern)
            | User.c.email.ilike(pattern)
            | User.c.display_name.ilike(pattern)
        )
    return query


async def member_page(
    db,
    organization_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: str | None = None,
) -> PageRecord:
    count_query = (
        sa.select(sa.func.count())
        .select_from(OrganizationMember)
        .join(User, User.c.id == OrganizationMember.c.user_id)
        .where(OrganizationMember.c.organization_id == organization_id)
    )
    if status is None:
        count_query = count_query.where(OrganizationMember.c.status != "left")
    else:
        count_query = count_query.where(OrganizationMember.c.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        count_query = count_query.where(
            User.c.username.ilike(pattern)
            | User.c.email.ilike(pattern)
            | User.c.display_name.ilike(pattern)
        )
    record = PageRecord(
        rows=[],
        total=int(await db.fetch_val(count_query)),
        page=page,
        page_size=page_size,
    )
    rows = await db.fetch_all(
        _member_query(organization_id, keyword, status)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    record.rows = [dict(row) for row in rows]
    return record


async def list_member_candidates(
    db,
    organization_id: int,
    tenant_id: int,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    query = (
        sa.select(User.c.id, User.c.username, User.c.email, User.c.display_name, User.c.avatar)
        .select_from(
            User.join(
                TenantMember,
                sa.and_(
                    TenantMember.c.user_id == User.c.id,
                    TenantMember.c.tenant_id == tenant_id,
                    TenantMember.c.status == "active",
                ),
            ).outerjoin(
                OrganizationMember,
                sa.and_(
                    OrganizationMember.c.user_id == User.c.id,
                    OrganizationMember.c.organization_id == organization_id,
                ),
            )
        )
        .where(User.c.status == "active", OrganizationMember.c.id.is_(None))
        .order_by(User.c.display_name.asc(), User.c.id.asc())
    )
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            User.c.username.ilike(pattern)
            | User.c.email.ilike(pattern)
            | User.c.display_name.ilike(pattern)
        )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


__all__ = (
    "insert_",
    "update_",
    "get",
    "list",
    "page",
    "count_children",
    "insert_member",
    "update_member",
    "get_member",
    "get_tenant_member",
    "member_page",
    "list_member_candidates",
)
