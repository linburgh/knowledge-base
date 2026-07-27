from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status

from app.core.common import auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import guest as guest_service
from app.core.common.auth import CurrentUser
from app.schemas.chat import GuestChatRequest
from app.schemas.conversation import GuestConversationModifyRequest

router = APIRouter()
current_user_dependency = Depends(auth.get_current_user)


@router.get("/knowledge-bases/page")
async def page_knowledge_bases(
    current_user: CurrentUser = current_user_dependency,
    keyword: str | None = Query(default=None, max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> Any:
    try:
        return await guest_service.page_knowledge_bases(
            current_user,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.post("/chat")
async def chat(
    payload: GuestChatRequest,
    current_user: CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await guest_service.chat(
            current_user,
            kb_id=payload.kb_id,
            question=payload.question,
            conversation_id=payload.conversation_id,
            top_k=payload.top_k,
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/conversations")
async def list_conversations(
    kb_id: int = Query(..., gt=0),
    current_user: CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await guest_service.list_conversations(current_user, kb_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.get("/conversations/{conversation_id}/messages")
async def list_conversation_messages(
    conversation_id: int,
    current_user: CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await guest_service.list_conversation_messages(
            current_user, conversation_id
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.put("/conversations/{conversation_id}")
async def modify_conversation(
    conversation_id: int,
    payload: GuestConversationModifyRequest,
    current_user: CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await guest_service.modify_conversation(
            current_user, conversation_id, payload.title
        )
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_200_OK)
async def remove_conversation(
    conversation_id: int,
    current_user: CurrentUser = current_user_dependency,
) -> Any:
    try:
        return await guest_service.remove_conversation(current_user, conversation_id)
    except BusiException as exc:
        common_utils.raise_http_exception(exc)


__all__ = ("router",)
