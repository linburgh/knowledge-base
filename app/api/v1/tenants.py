from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import tenant as tenant_service
from app.core.services import tenant_member as tenant_member_service
from app.schemas.tenant import TenantCreateRequest, TenantDto, TenantModifyRequest
from app.schemas.tenant_member import TenantMemberModifyRequest, TenantMemberRequest

router = APIRouter()


@router.get("/{id}/members/page")
async def member_page(
    id: int,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Any:
    try:
        return await tenant_member_service.page(id, keyword, status, page, page_size)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}/member-candidates")
async def member_candidates(id: int, keyword: str | None = None) -> Any:
    try:
        return await tenant_member_service.candidates(id, keyword)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(id: int, payload: TenantMemberRequest) -> Any:
    try:
        return await tenant_member_service.add(id, payload.model_dump())
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}/members/{member_id}")
async def modify_member(id: int, member_id: int, payload: TenantMemberModifyRequest) -> Any:
    try:
        return await tenant_member_service.modify(
            id, member_id, payload.model_dump(exclude_unset=True)
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}/members/{member_id}")
async def remove_member(id: int, member_id: int) -> Any:
    try:
        return await tenant_member_service.remove(id, member_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


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
