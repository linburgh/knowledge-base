from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import platform_role as platform_role_service
from app.api.v1.dependencies import require_platform_super_admin
from app.schemas.platform_role import PlatformRoleAssignmentRequest, PlatformRoleResponse

router = APIRouter(dependencies=[Depends(require_platform_super_admin)])


@router.get("/roles", response_model=list[PlatformRoleResponse])
async def list_roles() -> Any:
    try:
        return await platform_role_service.list()
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/users/{user_id}/roles", response_model=list[PlatformRoleResponse])
async def get_user_roles(user_id: int) -> Any:
    try:
        return await platform_role_service.get_user_roles(user_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/users/{user_id}/roles", response_model=list[PlatformRoleResponse])
async def assign_user_roles(user_id: int, payload: PlatformRoleAssignmentRequest) -> Any:
    try:
        return await platform_role_service.assign_user_roles(user_id, payload.role_codes)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
