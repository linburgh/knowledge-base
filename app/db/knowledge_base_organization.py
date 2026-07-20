from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.base import PageRecord
from app.db.models import KnowledgeBaseOrganization, Organization


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBaseOrganization, **kwargs)


async def delete_(db, **kwargs: Any) -> Any:
    return await db_api.delete_(db, KnowledgeBaseOrganization, **kwargs)


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, KnowledgeBaseOrganization, **kwargs)


async def list(db, kb_id: int) -> list[dict[str, Any]]:
    query = (
        sa.select(KnowledgeBaseOrganization, Organization.c.name.label("organization_name"))
        .select_from(
            KnowledgeBaseOrganization.join(
                Organization,
                Organization.c.id == KnowledgeBaseOrganization.c.organization_id,
            )
        )
        .where(KnowledgeBaseOrganization.c.kb_id == kb_id)
        .order_by(Organization.c.name.asc(), Organization.c.id.asc())
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

    parent = Organization.alias("parent_organization")
    grant = KnowledgeBaseOrganization.alias("knowledge_base_organization_grant")
    source = (
        Organization.outerjoin(parent, Organization.c.parent_id == parent.c.id)
        .outerjoin(
            grant,
            sa.and_(
                grant.c.kb_id == kb_id,
                grant.c.organization_id == Organization.c.id,
            ),
        )
    )
    conditions = [
        Organization.c.tenant_id == tenant_id,
        Organization.c.status != "deleted",
        grant.c.id.is_(None),
    ]
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            sa.or_(
                Organization.c.name.ilike(pattern),
                Organization.c.code.ilike(pattern),
                parent.c.name.ilike(pattern),
                parent.c.code.ilike(pattern),
            )
        )
    count_query = sa.select(sa.func.count()).select_from(source).where(*conditions)
    total = int(await db.fetch_val(count_query))
    query = (
        sa.select(
            Organization,
            parent.c.name.label("parent_name"),
            parent.c.code.label("parent_code"),
        )
        .select_from(source)
        .where(*conditions)
        .order_by(Organization.c.name.asc(), Organization.c.id.asc())
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
