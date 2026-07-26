from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import (
    KnowledgeBaseUser,
    Organization,
    OrganizationMember,
    TenantMember,
    User,
)


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBaseUser, **kwargs)


async def delete_(db, **kwargs: Any) -> Any:
    return await db_api.delete_(db, KnowledgeBaseUser, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, KnowledgeBaseUser, **kwargs)


async def list(db, kb_id: int) -> list[dict[str, Any]]:
    query = (
        sa.select(
            KnowledgeBaseUser,
            User.c.username,
            User.c.email,
            User.c.display_name,
        )
        .select_from(KnowledgeBaseUser.join(User, User.c.id == KnowledgeBaseUser.c.user_id))
        .where(KnowledgeBaseUser.c.kb_id == kb_id)
        .order_by(User.c.display_name.asc(), User.c.id.asc())
    )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def available_page(
    db,
    kb_id: int,
    tenant_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
) -> PageRecord:

    organization_name = (
        sa.select(Organization.c.name)
        .select_from(
            OrganizationMember.join(
                Organization,
                Organization.c.id == OrganizationMember.c.organization_id,
            )
        )
        .where(
            OrganizationMember.c.user_id == User.c.id,
            OrganizationMember.c.status == "active",
            Organization.c.tenant_id == tenant_id,
            Organization.c.status != "deleted",
        )
        .order_by(OrganizationMember.c.is_primary.desc(), OrganizationMember.c.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    tenant_member_exists = sa.exists(
        sa.select(1).select_from(TenantMember).where(
            TenantMember.c.tenant_id == tenant_id,
            TenantMember.c.user_id == User.c.id,
            TenantMember.c.status == "active",
        )
    )
    grant_exists = sa.exists(
        sa.select(1).select_from(KnowledgeBaseUser).where(
            KnowledgeBaseUser.c.kb_id == kb_id,
            KnowledgeBaseUser.c.user_id == User.c.id,
        )
    )
    conditions = [
        User.c.status == "active",
        tenant_member_exists,
        ~grant_exists,
    ]
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            sa.or_(
                User.c.username.ilike(pattern),
                User.c.email.ilike(pattern),
                User.c.display_name.ilike(pattern),
            )
        )
    count_query = sa.select(sa.func.count()).select_from(User).where(*conditions)
    total = int(await db.fetch_val(count_query))
    query = (
        sa.select(
            User.c.id,
            User.c.username,
            User.c.email,
            User.c.phone,
            User.c.display_name,
            User.c.avatar,
            User.c.external_subject,
            User.c.status,
            User.c.last_login_at,
            User.c.created_at,
            User.c.updated_at,
            organization_name.label("organization_name"),
        )
        .select_from(User)
        .where(*conditions)
        .order_by(User.c.display_name.asc(), User.c.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = await db.fetch_all(query)
    return PageRecord(
        rows=[dict(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


__all__ = ("available_page", "delete_", "get", "insert_", "list")
