from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.core.common.time_range import resolve_range
from app.db import platform_overview as platform_overview_db
from app.db.api import check_db_connected
from app.db.base import DB


def _resolve_range(
    range_name: str,
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime, datetime]:
    return resolve_range(range_name, start_at, end_at)


@check_db_connected
async def get_overview(
    range_name: str = "7d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    tenant_limit: int = 5,
) -> dict[str, Any]:
    start_at, end_at = _resolve_range(range_name, start_at, end_at)
    db = DB.get()
    (
        metrics,
        user_trend,
        kb_trend,
        tenant_resources,
        document_status,
        activities,
    ) = await asyncio.gather(
        platform_overview_db.metrics(db),
        platform_overview_db.user_trend(db, start_at, end_at),
        platform_overview_db.knowledge_base_trend(db, start_at, end_at),
        platform_overview_db.tenant_resources(db, limit=tenant_limit),
        platform_overview_db.document_status(db),
        platform_overview_db.recent_activities(db),
    )
    return {
        "range": range_name,
        "start_at": start_at,
        "end_at": end_at,
        "metrics": metrics,
        "user_trend": user_trend,
        "tenant_resources": tenant_resources,
        "knowledge_base_trend": kb_trend,
        "document_status": document_status,
        "recent_activities": activities,
    }


__all__ = ("get_overview",)
