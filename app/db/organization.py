from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import Organization, OrganizationMember, TenantMember, User


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, Organization, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, Organization, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, Organization, **kwargs)


async def list(
    db,
    tenant_id: int,
    keyword: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    member_count = sa.func.count(
        sa.distinct(OrganizationMember.c.id)
    ).filter(OrganizationMember.c.status == "active")
    query = (
        sa.select(Organization, member_count.label("member_count"))
        .select_from(Organization)
        .outerjoin(
            OrganizationMember,
            OrganizationMember.c.organization_id == Organization.c.id,
        )
        .where(Organization.c.tenant_id == tenant_id)
        .group_by(*Organization.c)
        .order_by(Organization.c.created_at.asc(), Organization.c.id.asc())
    )
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


__all__ = (
    "insert_",
    "update_",
    "get",
    "list",
    "count_children",
    "insert_member",
    "update_member",
    "get_member",
    "get_tenant_member",
    "member_page",
)
