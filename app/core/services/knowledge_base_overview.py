from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.core.common.exception import BusiException
from app.core.common.time_range import resolve_range
from app.db import knowledge_base as knowledge_base_db
from app.db import knowledge_base_overview as overview_db
from app.db.api import check_db_connected
from app.db.base import DB


@check_db_connected
async def get_overview(
    knowledge_base_id: int,
    range_name: str = "7d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    if not knowledge_base_id:
        raise BusiException("knowledge_base_id 不能为空")
    start_at, end_at = resolve_range(range_name, start_at, end_at)

    db = DB.get()
    knowledge_base = await knowledge_base_db.get(db, id=knowledge_base_id)
    if knowledge_base is None or knowledge_base.get("status") == "deleted":
        raise BusiException("知识库不存在", status_code=404)

    (
        metrics,
        document_trend,
        document_status,
        qa_trend,
        quality,
        hot_questions,
        document_ranking,
        activities,
    ) = await asyncio.gather(
        overview_db.metrics(db, knowledge_base_id),
        overview_db.document_trend(db, knowledge_base_id, start_at, end_at),
        overview_db.document_status(db, knowledge_base_id),
        overview_db.qa_trend(db, knowledge_base_id, start_at, end_at),
        overview_db.quality(db, knowledge_base_id, start_at, end_at),
        overview_db.hot_questions(db, knowledge_base_id, start_at, end_at),
        overview_db.document_ranking(db, knowledge_base_id, start_at, end_at),
        overview_db.recent_activities(db, knowledge_base_id),
    )
    return {
        "kb_id": knowledge_base_id,
        "range": range_name,
        "start_at": start_at,
        "end_at": end_at,
        "metrics": metrics,
        "document_trend": document_trend,
        "document_status": document_status,
        "qa_trend": qa_trend,
        "quality": quality,
        "hot_questions": hot_questions,
        "document_ranking": document_ranking,
        "recent_activities": activities,
    }


__all__ = ("get_overview",)
