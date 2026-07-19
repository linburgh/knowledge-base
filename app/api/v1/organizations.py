from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import organization as organization_service
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationDto,
    OrganizationMemberDto,
    OrganizationMemberModifyRequest,
    OrganizationMemberRequest,
    OrganizationModifyRequest,
)

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(payload: OrganizationCreateRequest) -> Any:
    try:
        return await organization_service.add(
            common_utils.parse_dataclass(payload, OrganizationDto)
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("")
async def tree(tenant_id: int, keyword: str | None = None, status: str | None = None) -> Any:
    try:
        return await organization_service.tree(tenant_id, keyword, status)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/tree")
async def tree_view(tenant_id: int, keyword: str | None = None, status: str | None = None) -> Any:
    try:
        return await organization_service.tree(tenant_id, keyword, status)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}")
async def modify(id: int, payload: OrganizationModifyRequest) -> Any:
    try:
        return await organization_service.modify(
            id,
            common_utils.parse_dataclass(payload, OrganizationDto),
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}")
async def remove(id: int) -> Any:
    try:
        return await organization_service.remove(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}/members/page")
async def member_page(
    id: int,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Any:
    try:
        return await organization_service.member_page(id, keyword, status, page, page_size)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(id: int, payload: OrganizationMemberRequest) -> Any:
    try:
        return await organization_service.add_member(
            id,
            common_utils.parse_dataclass(payload, OrganizationMemberDto),
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}/members/{member_id}")
async def modify_member(
    id: int,
    member_id: int,
    payload: OrganizationMemberModifyRequest,
) -> Any:
    try:
        return await organization_service.modify_member(
            member_id,
            common_utils.parse_dataclass(payload, OrganizationMemberDto),
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}/members/{member_id}")
async def remove_member(id: int, member_id: int) -> Any:
    try:
        return await organization_service.remove_member(member_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}")
async def get(id: int) -> Any:
    try:
        return await organization_service.get(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
