from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.v1.dependencies import (
    require_platform_management,
    require_platform_super_admin,
)
from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services.platform import organization as organization_service
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationDto,
    OrganizationMemberDto,
    OrganizationMemberModifyRequest,
    OrganizationMemberRequest,
    OrganizationModifyRequest,
)
from app.schemas.organization_member import OrganizationMemberBatchRequest

router = APIRouter()
current_user_dependency = Depends(auth.get_current_user)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_platform_super_admin)],
)
async def add(payload: OrganizationCreateRequest) -> Any:
    try:
        return await organization_service.add(
            common_utils.parse_dataclass(payload, OrganizationDto)
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("", dependencies=[Depends(require_platform_management)])
async def tree(
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.tree(current_user, tenant_id, keyword, status)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/tree", dependencies=[Depends(require_platform_management)])
async def tree_view(
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.tree(current_user, tenant_id, keyword, status)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/page", dependencies=[Depends(require_platform_management)])
async def page(
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.page(
            current_user, tenant_id, keyword, status, page, page_size
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/tree/parents", dependencies=[Depends(require_platform_management)])
async def tree_parents(
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    page_size: int = 20,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.tree_parents_page(
            current_user,
            tenant_id=tenant_id,
            keyword=keyword,
            status=status,
            cursor=cursor,
            page_size=page_size,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/tree/locate", dependencies=[Depends(require_platform_management)])
async def locate_search(
    tenant_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
    limit: int = 20,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.locate_search(
            current_user,
            tenant_id=tenant_id,
            keyword=keyword,
            status=status,
            limit=limit,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/tree/locate/{id}", dependencies=[Depends(require_platform_management)])
async def locate_context(
    id: int,
    status: str | None = None,
    page_size: int = 5,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.locate_context(
            current_user,
            organization_id=id,
            status=status,
            page_size=page_size,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/tree/locate/{id}/siblings", dependencies=[Depends(require_platform_management)])
async def locate_siblings(
    id: int,
    direction: str,
    cursor: str | None = None,
    status: str | None = None,
    page_size: int = 5,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.locate_siblings(
            current_user,
            organization_id=id,
            direction=direction,
            cursor=cursor,
            status=status,
            page_size=page_size,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/tree/locate/{id}/ancestor-page", dependencies=[Depends(require_platform_management)])
async def locate_ancestor_page(
    id: int,
    ancestor_id: int,
    cursor: str | None = None,
    status: str | None = None,
    page_size: int = 5,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.locate_ancestor_page(
            current_user,
            organization_id=id,
            ancestor_id=ancestor_id,
            cursor=cursor,
            status=status,
            page_size=page_size,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}/children", dependencies=[Depends(require_platform_management)])
async def tree_children(
    id: int,
    keyword: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    page_size: int = 20,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await organization_service.tree_children_page(
            current_user,
            parent_id=id,
            keyword=keyword,
            status=status,
            cursor=cursor,
            page_size=page_size,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}", dependencies=[Depends(require_platform_super_admin)])
async def modify(id: int, payload: OrganizationModifyRequest) -> Any:
    try:
        return await organization_service.modify(
            id,
            common_utils.parse_dataclass(payload, OrganizationDto),
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}", dependencies=[Depends(require_platform_super_admin)])
async def remove(id: int) -> Any:
    try:
        return await organization_service.remove(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}/members/page", dependencies=[Depends(require_platform_super_admin)])
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


@router.post(
    "/{id}/members",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_platform_super_admin)],
)
async def add_member(id: int, payload: OrganizationMemberRequest) -> Any:
    try:
        return await organization_service.add_member(
            id,
            common_utils.parse_dataclass(payload, OrganizationMemberDto),
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}/member-candidates", dependencies=[Depends(require_platform_super_admin)])
async def member_candidates(id: int, keyword: str | None = None) -> Any:
    try:
        return await organization_service.member_candidates(id, keyword)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}/member-candidates/page", dependencies=[Depends(require_platform_super_admin)])
async def member_candidate_page(
    id: int,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Any:
    try:
        return await organization_service.member_candidate_page(id, keyword, page, page_size)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}/members/batch", dependencies=[Depends(require_platform_super_admin)])
async def batch_members(id: int, payload: OrganizationMemberBatchRequest) -> Any:
    try:
        return await organization_service.batch_members(id, payload.members)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}/members/{member_id}", dependencies=[Depends(require_platform_super_admin)])
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


@router.delete("/{id}/members/{member_id}", dependencies=[Depends(require_platform_super_admin)])
async def remove_member(id: int, member_id: int) -> Any:
    try:
        return await organization_service.remove_member(member_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}", dependencies=[Depends(require_platform_super_admin)])
async def get(id: int) -> Any:
    try:
        return await organization_service.get(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
