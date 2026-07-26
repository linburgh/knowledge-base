from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.common import access, auth
from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.core.services import conversation as conversation_service
from app.core.services import guest as guest_service
from app.core.services import retrieval as retrieval_service
from app.api.open.dependencies import rate_limit
from app.db import conversation as conversation_db
from app.db import conversation_message as conversation_message_db
from app.db.base import DB
from app.schemas.conversation import ConversationMessageDto
from app.schemas.open import OpenChatRequest, OpenMessageRequest, OpenSearchRequest

router = APIRouter(dependencies=[Depends(rate_limit)])
current_user_dependency = Depends(auth.get_current_user)


@router.get("/knowledge-bases")
async def list_knowledge_bases(
    current_user: auth.CurrentUser = current_user_dependency,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> Any:
    record = await guest_service.page_knowledge_bases(current_user, keyword, page, page_size)
    return {"items": record.rows, "total": record.total, "page": record.page, "page_size": record.page_size}


@router.post("/search")
async def search(payload: OpenSearchRequest, current_user: auth.CurrentUser = current_user_dependency) -> Any:
    await access.require_knowledge_base_access(current_user, payload.knowledge_base_id)
    return await retrieval_service.search(
        kb_id=payload.knowledge_base_id,
        query=payload.query,
        top_k=payload.top_k,
        mode=payload.mode,
    )


@router.post("/chat")
async def chat(payload: OpenChatRequest, current_user: auth.CurrentUser = current_user_dependency) -> Any:
    return await guest_service.chat(
        current_user,
        kb_id=payload.knowledge_base_id,
        question=payload.question,
        conversation_id=payload.conversation_id,
        top_k=payload.top_k,
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    await guest_service._authorized_conversation(current_user, conversation_id)
    conversation = await conversation_db.get(DB.get(), id=conversation_id)
    if conversation is None:
        raise BusiException("会话不存在", status_code=404)
    return conversation


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    return await guest_service.list_conversation_messages(current_user, conversation_id)


@router.post("/conversations/{conversation_id}/messages")
async def add_message(
    conversation_id: int,
    payload: OpenMessageRequest,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    conversation = await guest_service._authorized_conversation(current_user, conversation_id)
    message = ConversationMessageDto(
        conversation_id=conversation_id,
        user_id=current_user.user_id,
        role="user",
        content=payload.content,
    )
    return await conversation_service.add_message(conversation["id"], message)


@router.get("/documents/{document_id}")
async def get_document(
    document_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    return await access.require_document_access(current_user, document_id)


@router.get("/documents/{document_id}/tasks/{task_id}")
async def get_task(
    document_id: int,
    task_id: int,
    current_user: auth.CurrentUser = current_user_dependency,
) -> Any:
    return await access.require_task_access(current_user, document_id, task_id)


__all__ = ("router",)
