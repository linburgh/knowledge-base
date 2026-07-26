from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import knowledge_base_overview as overview_service
from app.schemas.knowledge_base_overview import KnowledgeBaseOverviewResponse

router = APIRouter(dependencies=[Depends(auth.get_current_user)])


@router.get("/{kb_id}/overview", response_model=KnowledgeBaseOverviewResponse)
async def overview(
    kb_id: int,
    range: str = "7d",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> Any:
    try:
        return await overview_service.get_overview(
            knowledge_base_id=kb_id,
            range_name=range,
            start_at=start_at,
            end_at=end_at,
            current_user=current_user,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
