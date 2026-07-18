from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import conversation as conversation_service
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationDto,
    ConversationMessageCreateRequest,
    ConversationMessageDto,
    ConversationMessageModifyRequest,
    ConversationModifyRequest,
    MessageCitationCreateRequest,
    MessageCitationDto,
    MessageCitationModifyRequest,
)

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def add(payload: ConversationCreateRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, ConversationDto)
        return await conversation_service.add(dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("")
async def list(
    kb_id: int | None = None,
    user_id: str | None = None,
    status: str | None = None,
) -> Any:
    try:
        return await conversation_service.list(
            kb_id=kb_id,
            user_id=user_id,
            status=status,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/messages/{id}")
async def get_message(id: int) -> Any:
    try:
        return await conversation_service.get_message(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/messages/{id}")
async def modify_message(id: int, payload: ConversationMessageModifyRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, ConversationMessageDto)
        return await conversation_service.modify_message(id, dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/messages/{id}")
async def remove_message(id: int) -> Any:
    try:
        return await conversation_service.remove_message(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/messages/{message_id}/citations", status_code=status.HTTP_201_CREATED)
async def add_citation(
    message_id: int,
    kb_id: int,
    payload: MessageCitationCreateRequest,
) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, MessageCitationDto)
        dto.kb_id = kb_id
        return await conversation_service.add_citation(message_id, dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/messages/{message_id}/citations")
async def list_citations(message_id: int) -> Any:
    try:
        return await conversation_service.list_citations(message_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/citations/{id}")
async def get_citation(id: int) -> Any:
    try:
        return await conversation_service.get_citation(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/citations/{id}")
async def modify_citation(id: int, payload: MessageCitationModifyRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, MessageCitationDto)
        return await conversation_service.modify_citation(id, dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/citations/{id}")
async def remove_citation(id: int) -> Any:
    try:
        return await conversation_service.remove_citation(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/{id}")
async def modify(id: int, payload: ConversationModifyRequest) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, ConversationDto)
        return await conversation_service.modify(id, dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/{id}")
async def remove(id: int) -> Any:
    try:
        return await conversation_service.remove(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{id}")
async def get(id: int) -> Any:
    try:
        return await conversation_service.get(id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def add_message(
    conversation_id: int,
    payload: ConversationMessageCreateRequest,
) -> Any:
    try:
        dto = common_utils.parse_dataclass(payload, ConversationMessageDto)
        return await conversation_service.add_message(conversation_id, dto)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/{conversation_id}/messages")
async def list_messages(conversation_id: int) -> Any:
    try:
        return await conversation_service.list_messages(conversation_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
