from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import tenant as tenant_service
from app.schemas.tenant import TenantCreateRequest, TenantDto, TenantModifyRequest

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(payload: TenantCreateRequest) -> Any:
    try:
        return await tenant_service.add(common_utils.parse_dataclass(payload, TenantDto))
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("")
async def list(code: str | None = None, status: str | None = None) -> Any:
    try:
        return await tenant_service.list(code=code, status=status)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/page")
async def page(
    code: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Any:
    try:
        return await tenant_service.page(code=code, status=status, page=page, page_size=page_size)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}")
async def modify(id: int, payload: TenantModifyRequest) -> Any:
    try:
        return await tenant_service.modify(id, common_utils.parse_dataclass(payload, TenantDto))
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}")
async def remove(id: int) -> Any:
    try:
        return await tenant_service.remove(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}")
async def get(id: int) -> Any:
    try:
        return await tenant_service.get(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
