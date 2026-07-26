from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import user as user_service
from app.api.v1.dependencies import require_platform_super_admin
from app.schemas.user import UserCreateRequest, UserDto, UserModifyRequest

router = APIRouter(dependencies=[Depends(require_platform_super_admin)])


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(payload: UserCreateRequest) -> Any:
    try:
        return await user_service.add(common_utils.parse_dataclass(payload, UserDto))
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("")
async def list(
    keyword: str | None = None,
    username: str | None = None,
    email: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> Any:
    try:
        return await user_service.list(
            keyword=keyword,
            username=username,
            email=email,
            status=status,
            tenant_id=tenant_id,
            organization_id=organization_id,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/page")
async def page(
    keyword: str | None = None,
    username: str | None = None,
    email: str | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Any:
    try:
        return await user_service.page(
            keyword=keyword,
            username=username,
            email=email,
            status=status,
            tenant_id=tenant_id,
            organization_id=organization_id,
            page=page,
            page_size=page_size,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}")
async def modify(id: int, payload: UserModifyRequest) -> Any:
    try:
        return await user_service.modify(id, common_utils.parse_dataclass(payload, UserDto))
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}")
async def remove(id: int) -> Any:
    try:
        return await user_service.remove(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}")
async def get(id: int) -> Any:
    try:
        return await user_service.get(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
