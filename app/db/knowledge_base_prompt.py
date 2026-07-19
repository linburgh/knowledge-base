from __future__ import annotations

from typing import Any

from app.db import api as db_api
from app.db.models import KnowledgeBasePrompt


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, KnowledgeBasePrompt, **kwargs)


async def list(db, **kwargs: Any) -> list[dict[str, Any]]:
    return await db_api.list(
        db,
        KnowledgeBasePrompt,
        order_by=[KnowledgeBasePrompt.c.version.desc(), KnowledgeBasePrompt.c.id.desc()],
        **kwargs,
    )


__all__ = ("insert_", "list")
