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
    parent_organization = Organization.alias("organization_parent")
    leader_user = User.alias("organization_page_leader")
    member_count = sa.func.count(
        sa.distinct(OrganizationMember.c.id)
    ).filter(OrganizationMember.c.status == "active")
    query = (
        sa.select(
            Organization,
            Tenant.c.name.label("tenant_name"),
            parent_organization.c.name.label("parent_name"),
            leader_user.c.display_name.label("leader_name"),
            leader_user.c.username.label("leader_username"),
            member_count.label("member_count"),
        )
        .select_from(Organization)
        .join(Tenant, Tenant.c.id == Organization.c.tenant_id)
        .outerjoin(parent_organization, parent_organization.c.id == Organization.c.parent_id)
        .outerjoin(leader_user, leader_user.c.id == Organization.c.leader_user_id)
        .outerjoin(
            OrganizationMember,
            OrganizationMember.c.organization_id == Organization.c.id,
        )
    )
    total_query = sa.select(sa.func.count()).select_from(Organization)
    tenant_join = Tenant.c.id == Organization.c.tenant_id
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
    query = (
        query.where(*conditions)
        .group_by(
            *Organization.c,
            Tenant.c.name,
            parent_organization.c.name,
            leader_user.c.display_name,
            leader_user.c.username,
        )
        .order_by(
            Organization.c.tenant_id.asc(),
            Organization.c.created_at.asc(),
            Organization.c.id.asc(),
        )
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


async def get_active_admin(db, organization_id: int, exclude_member_id: int | None = None):
    query = sa.select(OrganizationMember).where(
        OrganizationMember.c.organization_id == organization_id,
        OrganizationMember.c.role_code == "org_admin",
        OrganizationMember.c.status == "active",
    )
    if exclude_member_id is not None:
        query = query.where(OrganizationMember.c.id != exclude_member_id)
    row = await db.fetch_one(query.limit(1))
    return dict(row) if row else None


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
    organization_names = (
        sa.select(sa.func.string_agg(Organization.c.name, sa.literal(", ")))
        .select_from(
            OrganizationMember.join(
                Organization,
                OrganizationMember.c.organization_id == Organization.c.id,
            )
        )
        .where(
            OrganizationMember.c.user_id == User.c.id,
            OrganizationMember.c.status == "active",
            Organization.c.tenant_id == tenant_id,
        )
        .scalar_subquery()
    )
    query = (
        sa.select(
            User.c.id,
            User.c.username,
            User.c.email,
            User.c.display_name,
            User.c.avatar,
            organization_names.label("organization_name"),
        )
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


async def page_member_candidates(
    db,
    organization_id: int,
    tenant_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
) -> PageRecord:
    organization_names = (
        sa.select(sa.func.string_agg(Organization.c.name, sa.literal(", ")))
        .select_from(
            OrganizationMember.join(
                Organization,
                OrganizationMember.c.organization_id == Organization.c.id,
            )
        )
        .where(
            OrganizationMember.c.user_id == User.c.id,
            OrganizationMember.c.status == "active",
            Organization.c.tenant_id == tenant_id,
        )
        .scalar_subquery()
    )
    from_query = User.join(
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
    conditions = [User.c.status == "active", OrganizationMember.c.id.is_(None)]
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            User.c.username.ilike(pattern)
            | User.c.email.ilike(pattern)
            | User.c.display_name.ilike(pattern)
        )
    total_query = sa.select(sa.func.count()).select_from(from_query).where(*conditions)
    query = (
        sa.select(
            User.c.id,
            User.c.username,
            User.c.email,
            User.c.display_name,
            User.c.avatar,
            organization_names.label("organization_name"),
        )
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


async def page_unbound(
    db,
    tenant_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
) -> PageRecord:
    parent = Organization.alias("unbound_organization_parent")
    source = Organization.outerjoin(parent, Organization.c.parent_id == parent.c.id)
    conditions = [
        sa.or_(Organization.c.tenant_id.is_(None), Organization.c.tenant_id != tenant_id),
        Organization.c.status != "deleted",
    ]
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            Organization.c.name.ilike(pattern) | Organization.c.code.ilike(pattern)
        )
    total = int(await db.fetch_val(sa.select(sa.func.count()).select_from(source).where(*conditions)))
    query = (
        sa.select(Organization, parent.c.name.label("parent_name"))
        .select_from(source)
        .where(*conditions)
        .order_by(Organization.c.name.asc(), Organization.c.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return PageRecord(
        rows=[dict(row) for row in await db.fetch_all(query)],
        total=total,
        page=page,
        page_size=page_size,
    )


async def bind_tenant(db, organization_ids: list[int], tenant_id: int) -> None:
    await db.execute(
        sa.update(Organization)
        .where(Organization.c.id.in_(organization_ids))
        .values(tenant_id=tenant_id, parent_id=None, updated_at=sa.func.now())
    )


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
    "get_active_admin",
    "get_tenant_member",
    "member_page",
    "list_member_candidates",
    "page_member_candidates",
    "page_unbound",
    "bind_tenant",
)
