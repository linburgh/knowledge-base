from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.models import KnowledgeBaseQaConfigAudit, KnowledgeBaseQaConfigVersion


async def insert_version(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBaseQaConfigVersion, **kwargs)


async def update_version(db, values: dict[str, Any], **kwargs: Any) -> Any:
    return await db_api.update_(db, KnowledgeBaseQaConfigVersion, values, **kwargs)


async def get_version(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, KnowledgeBaseQaConfigVersion, **kwargs)


async def list_versions(db, kb_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        KnowledgeBaseQaConfigVersion,
        order_by=[
            KnowledgeBaseQaConfigVersion.c.version_no.desc(),
            KnowledgeBaseQaConfigVersion.c.id.desc(),
        ],
        limit=limit,
        kb_id=kb_id,
    )


async def next_version_no(db, kb_id: int) -> int:
    query = sa.select(sa.func.coalesce(sa.func.max(KnowledgeBaseQaConfigVersion.c.version_no), 0))
    query = query.where(KnowledgeBaseQaConfigVersion.c.kb_id == kb_id)
    return int(await db.fetch_val(query)) + 1


async def insert_audit(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBaseQaConfigAudit, **kwargs)


__all__ = (
    "get_version",
    "insert_audit",
    "insert_version",
    "list_versions",
    "next_version_no",
    "update_version",
)
