from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
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


__all__ = ("delete_", "get", "insert_", "list")
