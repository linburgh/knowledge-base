from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import knowledge_base as knowledge_base_service
from app.schemas.knowledge_base import KnowledgeBaseDto, KnowledgeBaseRequest
from app.schemas.knowledge_base_organization import KnowledgeBaseOrganizationRequest

router = APIRouter()
current_user_dependency = Depends(auth.get_current_user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(payload: KnowledgeBaseRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, KnowledgeBaseDto)
        return await knowledge_base_service.add(dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("")
async def list(
    name: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> Any:
    try:
        return await knowledge_base_service.list(
            name=name,
            owner_id=owner_id,
            status=status,
            visibility=visibility,
            tenant_id=tenant_id,
            organization_id=organization_id,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/page")
async def page(
    name: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    page: int = 1,
    page_size: int = 20,
    tenant_id: int | None = None,
    organization_id: int | None = None,
) -> Any:
    try:
        return await knowledge_base_service.page(
            name=name,
            owner_id=owner_id,
            status=status,
            visibility=visibility,
            page=page,
            page_size=page_size,
            tenant_id=tenant_id,
            organization_id=organization_id,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}")
async def modify(id: int, payload: KnowledgeBaseRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, KnowledgeBaseDto)
        return await knowledge_base_service.modify(id, dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}")
async def remove(id: int) -> Any:
    try:
        return await knowledge_base_service.remove(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}")
async def get(id: int) -> Any:
    try:
        return await knowledge_base_service.get(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}/prompt-history")
async def prompt_history(id: int) -> Any:
    try:
        return await knowledge_base_service.prompt_history(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}/organizations")
async def organization_grants(id: int) -> Any:
    try:
        return await knowledge_base_service.organization_grants(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{id}/organizations", status_code=status.HTTP_201_CREATED)
async def grant_organization(
    id: int,
    payload: KnowledgeBaseOrganizationRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await knowledge_base_service.grant_organization(
            id, payload.organization_id, created_by=int(current_user.user_id)
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}/organizations/{organization_id}")
async def revoke_organization(id: int, organization_id: int) -> Any:
    try:
        return await knowledge_base_service.revoke_organization(id, organization_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
