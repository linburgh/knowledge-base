from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.core.common.auth import CurrentUser
from app.core.common.roles import is_platform_super_admin
from app.core.common.time_range import resolve_range
from app.db import platform_overview as platform_overview_db
from app.db import user as user_db
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
    current_user: CurrentUser | None = None,
    range_name: str = "7d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    tenant_limit: int = 5,
) -> dict[str, Any]:
    start_at, end_at = _resolve_range(range_name, start_at, end_at)
    db = DB.get()
    tenant_id = None
    if current_user is not None:
        context = await user_db.get_auth_context(
            db,
            int(current_user.user_id),
            current_user.tenant_id,
        )
        if not is_platform_super_admin(context):
            tenant_id = current_user.tenant_id
            if tenant_id is None:
                raise ValueError("tenant_admin 当前租户不能为空")
    (
        metrics,
        user_trend,
        kb_trend,
        tenant_resources,
        document_status,
        activities,
    ) = await asyncio.gather(
        platform_overview_db.metrics(db, tenant_id=tenant_id),
        platform_overview_db.user_trend(db, start_at, end_at, tenant_id=tenant_id),
        platform_overview_db.knowledge_base_trend(
            db, start_at, end_at, tenant_id=tenant_id
        ),
        platform_overview_db.tenant_resources(
            db, limit=tenant_limit, tenant_id=tenant_id
        ),
        platform_overview_db.document_status(db, tenant_id=tenant_id),
        platform_overview_db.recent_activities(db, tenant_id=tenant_id),
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
