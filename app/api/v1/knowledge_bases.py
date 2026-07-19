from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import knowledge_base as knowledge_base_service
from app.schemas.knowledge_base import KnowledgeBaseDto, KnowledgeBaseRequest

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(payload: KnowledgeBaseRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, KnowledgeBaseDto)
        return await knowledge_base_service.add(dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("")
async def list(
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
) -> Any:
    try:
        return await knowledge_base_service.list(
            owner_id=owner_id,
            status=status,
            visibility=visibility,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/page")
async def page(
    owner_id: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Any:
    try:
        return await knowledge_base_service.page(
            owner_id=owner_id,
            status=status,
            visibility=visibility,
            page=page,
            page_size=page_size,
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


__all__ = ("router",)
