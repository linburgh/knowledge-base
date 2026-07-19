from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import OrganizationMember, TenantMember, User

STATUS_DELETED = "deleted"


def _conditions(
    keyword: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> list[Any]:
    conditions: list[Any] = []
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(User.c.username.ilike(pattern) | User.c.email.ilike(pattern))
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
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
):
    query = sa.select(User).select_from(User)
    if tenant_id is not None:
        query = query.join(TenantMember, TenantMember.c.user_id == User.c.id)
    if organization_id is not None:
        query = query.join(OrganizationMember, OrganizationMember.c.user_id == User.c.id)
    conditions = _conditions(keyword, status, tenant_id, organization_id)
    if conditions:
        query = query.where(sa.and_(*conditions))
    return query.distinct().order_by(User.c.created_at.desc(), User.c.id.desc())


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, User, **kwargs)


async def update_(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, User, values, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, User, **kwargs)


async def get_by_account(db, account: str) -> dict[str, Any] | None:
    query = sa.select(User).where(
        sa.or_(User.c.username == account, User.c.email == account)
    ).limit(1)
    row = await db.fetch_one(query)
    return dict(row) if row else None


async def list(
    db,
    keyword: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    rows = await db.fetch_all(_query(keyword, status, tenant_id, organization_id))
    return [dict(row) for row in rows]


async def page(
    db,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> PageRecord:
    query = _query(keyword, status, tenant_id, organization_id)
    count_query = sa.select(sa.func.count(sa.distinct(User.c.id))).select_from(User)
    if tenant_id is not None:
        count_query = count_query.join(TenantMember, TenantMember.c.user_id == User.c.id)
    if organization_id is not None:
        count_query = count_query.join(
            OrganizationMember,
            OrganizationMember.c.user_id == User.c.id,
        )
    conditions = _conditions(keyword, status, tenant_id, organization_id)
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


__all__ = ("insert_", "update_", "get", "get_by_account", "list", "page")
