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


async def organization_path(db, *, organization_id: int) -> list[dict[str, Any]]:
    path = (
        sa.select(
            Organization.c.id,
            Organization.c.parent_id,
            Organization.c.tenant_id,
            sa.cast(0, sa.Integer).label("depth"),
        )
        .where(Organization.c.id == organization_id)
        .cte("organization_path", recursive=True)
    )
    parent = Organization.alias("organization_path_parent")
    path = path.union_all(
        sa.select(
            parent.c.id,
            parent.c.parent_id,
            parent.c.tenant_id,
            (sa.cast(path.c.depth, sa.Integer) + sa.cast(1, sa.Integer)).label("depth"),
        )
        .select_from(path.join(parent, parent.c.id == path.c.parent_id))
        .where(
            parent.c.tenant_id == path.c.tenant_id,
            path.c.depth < 100,
        )
    )
    query = (
        sa.select(Organization)
        .select_from(Organization.join(path, Organization.c.id == path.c.id))
        .order_by(path.c.depth.asc())
    )
    return [dict(row) for row in await db.fetch_all(query)]


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


def _tree_query_base():
    leader_user = User.alias("organization_tree_leader")
    return leader_user


async def tree_parents(
    db,
    *,
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
    cursor: tuple[Any, ...] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    leader_user = _tree_query_base()
    query = (
        sa.select(
            Organization,
            Tenant.c.name.label("tenant_name"),
            leader_user.c.display_name.label("leader_name"),
            leader_user.c.username.label("leader_username"),
        )
        .select_from(Organization)
        .join(Tenant, Tenant.c.id == Organization.c.tenant_id)
        .outerjoin(leader_user, leader_user.c.id == Organization.c.leader_user_id)
        .where(Organization.c.parent_id.is_(None), Tenant.c.status != "deleted")
    )
    conditions = []
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
    if cursor is not None:
        if tenant_id is None:
            cursor_tenant_id, cursor_created_at, cursor_id = cursor
            conditions.append(
                sa.or_(
                    Organization.c.tenant_id > cursor_tenant_id,
                    sa.and_(
                        Organization.c.tenant_id == cursor_tenant_id,
                        Organization.c.created_at > cursor_created_at,
                    ),
                    sa.and_(
                        Organization.c.tenant_id == cursor_tenant_id,
                        Organization.c.created_at == cursor_created_at,
                        Organization.c.id > cursor_id,
                    ),
                )
            )
        else:
            cursor_created_at, cursor_id = cursor
            conditions.append(
                sa.or_(
                    Organization.c.created_at > cursor_created_at,
                    sa.and_(
                        Organization.c.created_at == cursor_created_at,
                        Organization.c.id > cursor_id,
                    ),
                )
            )
    if tenant_id is None:
        order_by = (
            Organization.c.tenant_id.asc(),
            Organization.c.created_at.asc(),
            Organization.c.id.asc(),
        )
    else:
        order_by = (Organization.c.created_at.asc(), Organization.c.id.asc())
    query = query.where(*conditions).order_by(*order_by).limit(limit + 1)
    return [dict(row) for row in await db.fetch_all(query)]


async def tree_parent_has_children(
    db,
    *,
    parent_ids: list[int],
    tenant_id: int | None = None,
) -> dict[int, bool]:
    if not parent_ids:
        return {}
    parent = Organization.alias("tree_parent")
    child = Organization.alias("tree_child")
    child_exists = sa.exists(
        sa.select(1)
        .select_from(child)
        .where(
            child.c.parent_id == parent.c.id,
            child.c.tenant_id == parent.c.tenant_id,
            child.c.status != "deleted",
        )
    )
    conditions = [parent.c.id.in_(parent_ids), parent.c.status != "deleted"]
    if tenant_id is not None:
        conditions.append(parent.c.tenant_id == tenant_id)
    query = sa.select(parent.c.id, child_exists.label("has_children")).where(*conditions)
    rows = await db.fetch_all(query)
    return {int(row["id"]): bool(row["has_children"]) for row in rows}


async def organization_member_counts(
    db,
    *,
    organization_ids: list[int],
) -> dict[int, int]:
    if not organization_ids:
        return {}
    query = (
        sa.select(
            OrganizationMember.c.organization_id,
            sa.func.count(sa.distinct(OrganizationMember.c.id)).label("member_count"),
        )
        .where(
            OrganizationMember.c.organization_id.in_(organization_ids),
            OrganizationMember.c.status == "active",
        )
        .group_by(OrganizationMember.c.organization_id)
    )
    rows = await db.fetch_all(query)
    return {int(row["organization_id"]): int(row["member_count"]) for row in rows}


async def tree_children(
    db,
    *,
    parent_id: int,
    tenant_id: int,
    keyword: str | None = None,
    status: str | None = None,
    cursor: tuple[Any, int] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    leader_user = User.alias("organization_child_leader")
    parent = Organization.alias("organization_child_parent")
    query = (
        sa.select(
            Organization,
            Tenant.c.name.label("tenant_name"),
            parent.c.name.label("parent_name"),
            leader_user.c.display_name.label("leader_name"),
            leader_user.c.username.label("leader_username"),
        )
        .select_from(Organization)
        .join(Tenant, Tenant.c.id == Organization.c.tenant_id)
        .join(parent, parent.c.id == Organization.c.parent_id)
        .outerjoin(leader_user, leader_user.c.id == Organization.c.leader_user_id)
        .where(
            Organization.c.parent_id == parent_id,
            Organization.c.tenant_id == tenant_id,
            Tenant.c.status != "deleted",
        )
    )
    conditions = []
    if status is None:
        conditions.append(Organization.c.status != "deleted")
    else:
        conditions.append(Organization.c.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            Organization.c.name.ilike(pattern) | Organization.c.code.ilike(pattern)
        )
    if cursor is not None:
        cursor_created_at, cursor_id = cursor
        conditions.append(
            sa.or_(
                Organization.c.created_at > cursor_created_at,
                sa.and_(
                    Organization.c.created_at == cursor_created_at,
                    Organization.c.id > cursor_id,
                ),
            )
    )
    query = (
        query.where(*conditions)
        .order_by(Organization.c.created_at.asc(), Organization.c.id.asc())
        .limit(limit + 1)
    )
    rows = [dict(row) for row in await db.fetch_all(query)]
    member_counts = await organization_member_counts(
        db,
        organization_ids=[int(row["id"]) for row in rows],
    )
    child_flags = await tree_parent_has_children(
        db,
        parent_ids=[int(row["id"]) for row in rows],
        tenant_id=tenant_id,
    )
    for row in rows:
        row["member_count"] = member_counts.get(int(row["id"]), 0)
        row["has_children"] = child_flags.get(int(row["id"]), False)
    return rows


def _locate_item_query(*, tenant_id: int | None = None):
    parent = Organization.alias("organization_locate_parent")
    query = (
        sa.select(
            Organization,
            Tenant.c.name.label("tenant_name"),
            parent.c.name.label("parent_name"),
        )
        .select_from(Organization)
        .join(Tenant, Tenant.c.id == Organization.c.tenant_id)
        .outerjoin(parent, parent.c.id == Organization.c.parent_id)
        .where(Tenant.c.status != "deleted", Organization.c.status != "deleted")
    )
    if tenant_id is not None:
        query = query.where(Organization.c.tenant_id == tenant_id)
    return query


async def locate_search(
    db,
    *,
    tenant_id: int | None = None,
    keyword: str,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query = _locate_item_query(tenant_id=tenant_id)
    if status is not None:
        query = query.where(Organization.c.status == status)
    pattern = f"%{keyword}%"
    query = query.where(
        Organization.c.name.ilike(pattern) | Organization.c.code.ilike(pattern)
    )
    query = query.order_by(
        Organization.c.tenant_id.asc(), Organization.c.created_at.asc(), Organization.c.id.asc()
    ).limit(limit)
    return [dict(row) for row in await db.fetch_all(query)]


async def locate_children(
    db,
    *,
    parent_id: int,
    tenant_id: int,
    target_id: int,
    direction: str,
    cursor: tuple[Any, int] | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query = _locate_item_query(tenant_id=tenant_id).where(
        Organization.c.parent_id == parent_id
    )
    if status is not None:
        query = query.where(Organization.c.status == status)
    target_query = sa.select(Organization.c.created_at, Organization.c.id).where(
        Organization.c.id == target_id,
        Organization.c.parent_id == parent_id,
        Organization.c.tenant_id == tenant_id,
    )
    target = await db.fetch_one(target_query)
    if target is None:
        return []
    anchor = cursor or (target["created_at"], target["id"])
    after_condition = sa.or_(
        Organization.c.created_at > anchor[0],
        sa.and_(
            Organization.c.created_at == anchor[0],
            Organization.c.id > anchor[1],
        ),
    )
    before_condition = sa.or_(
        Organization.c.created_at < anchor[0],
        sa.and_(
            Organization.c.created_at == anchor[0],
            Organization.c.id < anchor[1],
        ),
    )
    if direction == "after":
        query = query.where(after_condition).order_by(
            Organization.c.created_at.asc(), Organization.c.id.asc()
        )
    elif direction == "before":
        if cursor is None:
            query = query.where(before_condition).order_by(
                Organization.c.created_at.desc(), Organization.c.id.desc()
            )
        else:
            target_condition = sa.or_(
                Organization.c.created_at < target["created_at"],
                sa.and_(
                    Organization.c.created_at == target["created_at"],
                    Organization.c.id < target["id"],
                ),
            )
            query = query.where(after_condition, target_condition).order_by(
                Organization.c.created_at.asc(), Organization.c.id.asc()
            )
    else:
        raise ValueError("direction must be before or after")
    rows = [dict(row) for row in await db.fetch_all(query.limit(limit + 1))]
    if direction == "before" and cursor is None:
        rows.reverse()
    return rows


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
    "tree_parents",
    "tree_children",
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
