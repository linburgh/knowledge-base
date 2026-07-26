from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import platform_overview as platform_overview_service
from app.api.v1.dependencies import require_platform_super_admin
from app.schemas.platform_overview import PlatformOverviewResponse

router = APIRouter(dependencies=[Depends(require_platform_super_admin)])


@router.get("/overview", response_model=PlatformOverviewResponse)
async def overview(
    range: str = "7d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    tenant_limit: int = Query(default=5, ge=1, le=20),
) -> Any:
    try:
        return await platform_overview_service.get_overview(
            range_name=range,
            start_at=start_at,
            end_at=end_at,
            tenant_limit=tenant_limit,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
