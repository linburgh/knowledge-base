from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.common.exception import BusiException
from app.core.services import knowledge_base as knowledge_base_service
from app.schemas.knowledge_base import KnowledgeBaseRequest

router = APIRouter()


def _to_dto(payload: KnowledgeBaseRequest) -> knowledge_base_service.KnowledgeDto:
    return knowledge_base_service.KnowledgeDto(**payload.model_dump())


def _raise_http_exception(exc: BusiException) -> None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=exc.message)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(payload: KnowledgeBaseRequest) -> Any:
    try:
        return await knowledge_base_service.add(_to_dto(payload))
    except BusiException as exc:
        _raise_http_exception(exc)


@router.put("/{knowledge_base_id}")
async def modify(knowledge_base_id: int, payload: KnowledgeBaseRequest) -> Any:
    try:
        return await knowledge_base_service.modify(knowledge_base_id, _to_dto(payload))
    except BusiException as exc:
        _raise_http_exception(exc)


@router.delete("/{knowledge_base_id}")
async def remove(knowledge_base_id: int) -> Any:
    try:
        return await knowledge_base_service.remove(knowledge_base_id)
    except BusiException as exc:
        _raise_http_exception(exc)


@router.get("/{knowledge_base_id}")
async def get(knowledge_base_id: int) -> Any:
    try:
        return await knowledge_base_service.get(knowledge_base_id)
    except BusiException as exc:
        _raise_http_exception(exc)


__all__ = ("router",)
