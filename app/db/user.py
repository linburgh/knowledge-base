from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import (
    Organization,
    OrganizationMember,
    PlatformRole,
    PlatformUserRole,
    Tenant,
    TenantMember,
    User,
)

STATUS_DELETED = "deleted"


def _conditions(
    keyword: str | None = None,
    username: str | None = None,
    email: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> list[Any]:
    conditions: list[Any] = []
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            User.c.username.ilike(pattern)
            | User.c.email.ilike(pattern)
            | User.c.display_name.ilike(pattern)
        )
    if username:
        conditions.append(User.c.username.ilike(f"%{username}%"))
    if email:
        conditions.append(User.c.email.ilike(f"%{email}%"))
    if status is not None:
        conditions.append(User.c.status == status)
    else:
        conditions.append(User.c.status != STATUS_DELETED)
    if tenant_id is not None:
        conditions.append(TenantMember.c.tenant_id == tenant_id)
    if organization_id is not None:
        conditions.append(OrganizationMember.c.organization_id == organization_id)
    return conditions


def _query(
    keyword: str | None = None,
    username: str | None = None,
    email: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
):
    query = sa.select(User).select_from(User)
    if tenant_id is not None:
        query = query.join(TenantMember, TenantMember.c.user_id == User.c.id)
    if organization_id is not None:
        query = query.join(OrganizationMember, OrganizationMember.c.user_id == User.c.id)
    conditions = _conditions(keyword, username, email, status, tenant_id, organization_id)
    if conditions:
        query = query.where(sa.and_(*conditions))
    return query.distinct().order_by(User.c.created_at.desc(), User.c.id.desc())


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, User, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, User, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, User, **kwargs)


async def get_with_context(db, user_id: int) -> dict[str, Any] | None:
    user = await get(db, id=user_id)
    if user is None:
        return None

    tenant_rows = await db.fetch_all(
        sa.select(
            Tenant.c.id.label("tenant_id"),
            Tenant.c.name.label("tenant_name"),
            TenantMember.c.role_code.label("tenant_role"),
        )
        .select_from(TenantMember.join(Tenant, Tenant.c.id == TenantMember.c.tenant_id))
        .where(TenantMember.c.user_id == user_id, TenantMember.c.status == "active")
        .order_by(TenantMember.c.is_primary.desc(), TenantMember.c.created_at.asc())
    )
    tenant = dict(tenant_rows[0]) if tenant_rows else None

    organization_query = (
        sa.select(
            Organization.c.id.label("organization_id"),
            Organization.c.tenant_id,
            Organization.c.parent_id,
            Organization.c.name.label("organization_name"),
            OrganizationMember.c.role_code.label("organization_role"),
        )
        .select_from(
            OrganizationMember.join(
                Organization,
                Organization.c.id == OrganizationMember.c.organization_id,
            )
        )
        .where(OrganizationMember.c.user_id == user_id, OrganizationMember.c.status == "active")
        .order_by(OrganizationMember.c.is_primary.desc(), OrganizationMember.c.created_at.asc())
    )
    organization_rows = await db.fetch_all(organization_query)
    organization = None
    if tenant:
        organization = next(
            (dict(row) for row in organization_rows if row["tenant_id"] == tenant["tenant_id"]),
            None,
        )
    if organization is None and organization_rows:
        organization = dict(organization_rows[0])

    organization_path = None
    if organization:
        organization_rows = await db.fetch_all(
            sa.select(
                Organization.c.id,
                Organization.c.parent_id,
                Organization.c.name,
            ).where(
                Organization.c.tenant_id == organization["tenant_id"],
                Organization.c.status != "deleted",
            )
        )
        by_id = {row["id"]: dict(row) for row in organization_rows}
        names = []
        current_id = organization["organization_id"]
        while current_id in by_id and current_id not in {item["id"] for item in names}:
            current = by_id[current_id]
            names.append(current)
            current_id = current["parent_id"]
        organization_path = " / ".join(item["name"] for item in reversed(names))

    platform_role = await db.fetch_one(
        sa.select(PlatformRole.c.code)
        .select_from(
            PlatformUserRole.join(
                PlatformRole,
                PlatformRole.c.id == PlatformUserRole.c.role_id,
            )
        )
        .where(PlatformUserRole.c.user_id == user_id, PlatformRole.c.status == "active")
        .order_by(PlatformRole.c.id.asc())
        .limit(1)
    )
    user.update(
        {
            "tenant_id": tenant["tenant_id"] if tenant else None,
            "tenant_name": tenant["tenant_name"] if tenant else None,
            "tenant_role": tenant["tenant_role"] if tenant else "member",
            "organization_id": organization["organization_id"] if organization else None,
            "organization_name": organization["organization_name"] if organization else None,
            "organization_path": organization_path,
            "organization_role": organization["organization_role"] if organization else "member",
            "platform_role": platform_role["code"] if platform_role else "none",
        }
    )
    return user


async def get_auth_context(
    db,
    user_id: int,
    tenant_id: int | None = None,
) -> dict[str, Any] | None:
    user = await get(db, id=user_id)
    if user is None:
        return None

    platform_rows = await db.fetch_all(
        sa.select(PlatformRole.c.code, PlatformRole.c.name, PlatformRole.c.description)
        .select_from(
            PlatformUserRole.join(PlatformRole, PlatformRole.c.id == PlatformUserRole.c.role_id)
        )
        .where(
            PlatformUserRole.c.user_id == user_id,
            PlatformRole.c.status == "active",
        )
        .order_by(PlatformRole.c.id.asc())
    )
    tenant_rows = await db.fetch_all(
        sa.select(
            Tenant.c.id,
            Tenant.c.code,
            Tenant.c.name,
            Tenant.c.status,
            TenantMember.c.role_code,
            TenantMember.c.is_primary,
        )
        .select_from(TenantMember.join(Tenant, Tenant.c.id == TenantMember.c.tenant_id))
        .where(
            TenantMember.c.user_id == user_id,
            TenantMember.c.status == "active",
            Tenant.c.status != "deleted",
        )
        .order_by(TenantMember.c.is_primary.desc(), TenantMember.c.created_at.asc())
    )
    organization_rows = await db.fetch_all(
        sa.select(
            Organization.c.id,
            Organization.c.tenant_id,
            Organization.c.parent_id,
            Organization.c.code,
            Organization.c.name,
            OrganizationMember.c.role_code,
            OrganizationMember.c.is_primary,
        )
        .select_from(
            OrganizationMember.join(
                Organization,
                Organization.c.id == OrganizationMember.c.organization_id,
            )
        )
        .where(
            OrganizationMember.c.user_id == user_id,
            OrganizationMember.c.status == "active",
            Organization.c.status != "deleted",
        )
        .order_by(OrganizationMember.c.is_primary.desc(), OrganizationMember.c.created_at.asc())
    )
    tenants = [dict(row) for row in tenant_rows]
    organizations = [dict(row) for row in organization_rows]
    current_tenant = next(
        (tenant for tenant in tenants if tenant_id is not None and tenant["id"] == tenant_id),
        tenants[0] if tenants else None,
    )
    if current_tenant is not None:
        organizations = [
            organization
            for organization in organizations
            if organization["tenant_id"] == current_tenant["id"]
        ]
    return {
        "user": user,
        "platform_roles": [dict(row) for row in platform_rows],
        "tenants": tenants,
        "current_tenant": current_tenant,
        "tenant_role": current_tenant.get("role_code") if current_tenant else None,
        "organizations": organizations,
    }


async def get_by_account(db, account: str) -> dict[str, Any] | None:
    query = sa.select(User).where(
        sa.or_(User.c.username == account, User.c.email == account)
    ).limit(1)
    row = await db.fetch_one(query)
    return dict(row) if row else None


async def list(
    db,
    keyword: str | None = None,
    username: str | None = None,
    email: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    rows = await db.fetch_all(_query(keyword, username, email, status, tenant_id, organization_id))
    return [dict(row) for row in rows]


async def page(
    db,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    username: str | None = None,
    email: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> PageRecord:
    query = _query(keyword, username, email, status, tenant_id, organization_id)
    count_query = sa.select(sa.func.count(sa.distinct(User.c.id))).select_from(User)
    if tenant_id is not None:
        count_query = count_query.join(TenantMember, TenantMember.c.user_id == User.c.id)
    if organization_id is not None:
        count_query = count_query.join(
            OrganizationMember,
            OrganizationMember.c.user_id == User.c.id,
        )
    conditions = _conditions(keyword, username, email, status, tenant_id, organization_id)
    if conditions:
        count_query = count_query.where(sa.and_(*conditions))

    record = PageRecord(
        rows=[],
        total=int(await db.fetch_val(count_query)),
        page=page,
        page_size=page_size,
    )
    rows = await db.fetch_all(query.limit(page_size).offset((page - 1) * page_size))
    record.rows = [dict(row) for row in rows]
    return record


__all__ = (
    "insert_",
    "update_",
    "get",
    "get_with_context",
    "get_by_account",
    "list",
    "page",
)
