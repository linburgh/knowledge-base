from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import Organization, OrganizationMember, TenantMember, User


def _query(
    tenant_id: int,
    keyword: str | None = None,
    status: str | None = None,
    role_code: str | None = None,
):
    organization_name = sa.func.string_agg(
        sa.distinct(Organization.c.name), sa.literal(", ")
    ).label("organization_name")
    query = (
        sa.select(
            TenantMember,
            User.c.username,
            User.c.email,
            User.c.display_name,
            User.c.avatar,
            User.c.status.label("user_status"),
            organization_name,
        )
        .select_from(
            TenantMember.join(User, User.c.id == TenantMember.c.user_id)
            .outerjoin(
                OrganizationMember,
                sa.and_(
                    OrganizationMember.c.user_id == TenantMember.c.user_id,
                    OrganizationMember.c.status == "active",
                ),
            )
            .outerjoin(Organization, Organization.c.id == OrganizationMember.c.organization_id)
        )
        .where(TenantMember.c.tenant_id == tenant_id)
        .group_by(
            *TenantMember.c,
            User.c.username,
            User.c.email,
            User.c.display_name,
            User.c.avatar,
            User.c.status,
        )
        .order_by(TenantMember.c.created_at.desc(), TenantMember.c.id.desc())
    )
    if status is None:
        query = query.where(TenantMember.c.status != "left")
    else:
        query = query.where(TenantMember.c.status == status)
    if role_code:
        query = query.where(TenantMember.c.role_code == role_code)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            User.c.username.ilike(pattern)
            | User.c.email.ilike(pattern)
            | User.c.display_name.ilike(pattern)
        )
    return query


async def page(
    db,
    tenant_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: str | None = None,
    role_code: str | None = None,
) -> PageRecord:
    count_query = sa.select(sa.func.count()).select_from(TenantMember).join(
        User, User.c.id == TenantMember.c.user_id
    ).where(TenantMember.c.tenant_id == tenant_id)
    if status is None:
        count_query = count_query.where(TenantMember.c.status != "left")
    else:
        count_query = count_query.where(TenantMember.c.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        count_query = count_query.where(
            User.c.username.ilike(pattern)
            | User.c.email.ilike(pattern)
            | User.c.display_name.ilike(pattern)
        )
    if role_code:
        count_query = count_query.where(TenantMember.c.role_code == role_code)
    record = PageRecord(
        rows=[],
        total=int(await db.fetch_val(count_query)),
        page=page,
        page_size=page_size,
    )
    rows = await db.fetch_all(
        _query(tenant_id, keyword, status, role_code)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    record.rows = [dict(row) for row in rows]
    return record


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, TenantMember, **kwargs)


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, TenantMember, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, TenantMember, values, **kwargs)


async def list_candidates(db, tenant_id: int, keyword: str | None = None) -> list[dict[str, Any]]:
    query = (
        sa.select(User.c.id, User.c.username, User.c.email, User.c.display_name, User.c.avatar)
        .select_from(User.outerjoin(TenantMember, sa.and_(
            TenantMember.c.user_id == User.c.id,
            TenantMember.c.tenant_id == tenant_id,
        )))
        .where(User.c.status == "active", TenantMember.c.id.is_(None))
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


async def page_candidates(
    db,
    tenant_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
) -> PageRecord:
    conditions = [User.c.status == "active", TenantMember.c.id.is_(None)]
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            User.c.username.ilike(pattern)
            | User.c.email.ilike(pattern)
            | User.c.display_name.ilike(pattern)
        )
    from_query = User.outerjoin(
        TenantMember,
        sa.and_(
            TenantMember.c.user_id == User.c.id,
            TenantMember.c.tenant_id == tenant_id,
        ),
    )
    total_query = sa.select(sa.func.count()).select_from(from_query).where(*conditions)
    query = (
        sa.select(User.c.id, User.c.username, User.c.email, User.c.display_name, User.c.avatar)
        .select_from(from_query)
        .where(*conditions)
        .order_by(User.c.display_name.asc(), User.c.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    record = PageRecord(
        rows=[],
        total=int(await db.fetch_val(total_query)),
        page=page,
        page_size=page_size,
    )
    record.rows = [dict(row) for row in await db.fetch_all(query)]
    return record


__all__ = ("get", "insert_", "list_candidates", "page", "page_candidates", "update_")
