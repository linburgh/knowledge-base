from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.common.exception import BusiException
from app.db import platform_overview as platform_overview_db
from app.db.api import check_db_connected
from app.db.base import DB

VALID_RANGES = {"7d": 7, "30d": 30, "90d": 90}


def _resolve_range(
    range_name: str,
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime, datetime]:
    if range_name not in (*VALID_RANGES, "custom"):
        raise BusiException("range 必须是 7d、30d、90d 或 custom")
    if range_name == "custom":
        if start_at is None or end_at is None:
            raise BusiException("custom 范围必须提供 start_at 和 end_at")
    else:
        if start_at is not None or end_at is not None:
            raise BusiException("预设范围不需要提供 start_at 或 end_at")
        end_at = datetime.now(UTC)
        start_at = end_at - timedelta(days=VALID_RANGES[range_name])
    assert start_at is not None and end_at is not None
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise BusiException("时间参数必须包含时区")
    if start_at >= end_at:
        raise BusiException("start_at 必须早于 end_at")
    return start_at, end_at


@check_db_connected
async def get_overview(
    range_name: str = "7d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    start_at, end_at = _resolve_range(range_name, start_at, end_at)
    db = DB.get()
    metrics, user_trend, kb_trend, tenant_resources, document_status, activities = await asyncio.gather(
        platform_overview_db.metrics(db),
        platform_overview_db.user_trend(db, start_at, end_at),
        platform_overview_db.knowledge_base_trend(db, start_at, end_at),
        platform_overview_db.tenant_resources(db),
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
