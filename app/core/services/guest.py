from __future__ import annotations

from typing import Any

from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services import chat as chat_service
from app.db import conversation as conversation_db
from app.db import conversation_message as conversation_message_db
from app.db import knowledge_base as knowledge_base_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB, PageRecord

STATUS_ACTIVE = "active"
STATUS_DELETED = "deleted"
MAX_PAGE_SIZE = 100
MAX_TITLE_LENGTH = 50


async def _access_context(current_user: CurrentUser) -> tuple[int, int, list[int]]:
    try:
        user_id = int(current_user.user_id)
    except (TypeError, ValueError):
        raise BusiException("当前用户无效", status_code=401) from None

    if current_user.tenant_id is None:
        raise BusiException("当前用户未选择租户", status_code=403)
    context = await user_db.get_auth_context(DB.get(), user_id, current_user.tenant_id)
    if context is None or not context.get("tenant_role"):
        raise BusiException("当前用户不是有效的租户成员", status_code=403)
    organization_ids = [
        int(item.get("organization_id", item.get("id")))
        for item in context.get("organizations", [])
        if item.get("organization_id", item.get("id")) is not None
    ]
    return user_id, current_user.tenant_id, organization_ids


async def _authorized_conversation(
    current_user: CurrentUser,
    conversation_id: int,
) -> dict[str, Any]:
    user_id, tenant_id, organization_ids = await _access_context(current_user)
    conversation = await conversation_db.get(DB.get(), id=conversation_id)
    if (
        conversation is None
        or conversation.get("status") == STATUS_DELETED
        or str(conversation.get("user_id")) != current_user.user_id
    ):
        raise BusiException("会话不存在", status_code=404)
    if await knowledge_base_db.guest_get(
        DB.get(), tenant_id, user_id, organization_ids, int(conversation["kb_id"])
    ) is None:
        raise BusiException("会话不存在", status_code=404)
    return conversation


@check_db_connected
async def page_knowledge_bases(
    current_user: CurrentUser,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> PageRecord:
    if page <= 0:
        raise BusiException("page 必须大于 0")
    if page_size <= 0 or page_size > MAX_PAGE_SIZE:
        raise BusiException(f"page_size 必须在 1 到 {MAX_PAGE_SIZE} 之间")
    user_id, tenant_id, organization_ids = await _access_context(current_user)
    normalized_keyword = keyword.strip() if keyword and keyword.strip() else None
    return await knowledge_base_db.guest_page(
        DB.get(),
        tenant_id=tenant_id,
        user_id=user_id,
        organization_ids=organization_ids,
        keyword=normalized_keyword,
        page=page,
        page_size=page_size,
    )


@check_db_connected
async def chat(
    current_user: CurrentUser,
    kb_id: int,
    question: str,
    conversation_id: int | None = None,
    top_k: int | None = None,
) -> Any:
    user_id, tenant_id, organization_ids = await _access_context(current_user)
    if await knowledge_base_db.guest_get(
        DB.get(), tenant_id, user_id, organization_ids, kb_id
    ) is None:
        raise BusiException("无权访问该知识库", status_code=403)
    return await chat_service.chat(
        kb_id=kb_id,
        question=question,
        user_id=current_user.user_id,
        conversation_id=conversation_id,
        top_k=top_k,
        tenant_id=tenant_id,
        organization_ids=organization_ids,
        access_level="tenant_member",
    )


@check_db_connected
async def list_conversations(current_user: CurrentUser, kb_id: int) -> list[dict[str, Any]]:
    user_id, tenant_id, organization_ids = await _access_context(current_user)
    if await knowledge_base_db.guest_get(
        DB.get(), tenant_id, user_id, organization_ids, kb_id
    ) is None:
        raise BusiException("无权访问该知识库", status_code=403)
    return await conversation_db.list(
        DB.get(),
        kb_id=kb_id,
        user_id=current_user.user_id,
        status__ne=STATUS_DELETED,
    )


@check_db_connected
async def list_conversation_messages(
    current_user: CurrentUser,
    conversation_id: int,
) -> list[dict[str, Any]]:
    await _authorized_conversation(current_user, conversation_id)
    return await conversation_message_db.list(
        DB.get(), conversation_id=conversation_id
    )


@check_db_connected
async def modify_conversation(
    current_user: CurrentUser,
    conversation_id: int,
    title: str,
) -> dict[str, Any]:
    conversation = await _authorized_conversation(current_user, conversation_id)
    normalized_title = title.strip()
    if not normalized_title:
        raise BusiException("title 不能为空")
    if len(normalized_title) > MAX_TITLE_LENGTH:
        raise BusiException("title 不能超过 50 个字符")
    db = DB.get()
    async with db.transaction():
        await conversation_db.update_(
            db,
            {"title": normalized_title},
            id=conversation["id"],
            user_id=current_user.user_id,
            status__ne=STATUS_DELETED,
        )
        result = await conversation_db.get(db, id=conversation["id"])
    if result is None:
        raise BusiException("会话不存在", status_code=404)
    return result


@check_db_connected
async def remove_conversation(
    current_user: CurrentUser,
    conversation_id: int,
) -> dict[str, Any]:
    conversation = await _authorized_conversation(current_user, conversation_id)
    db = DB.get()
    async with db.transaction():
        await conversation_db.update_(
            db,
            {"status": STATUS_DELETED},
            id=conversation["id"],
            user_id=current_user.user_id,
            status__ne=STATUS_DELETED,
        )
        result = await conversation_db.get(db, id=conversation["id"])
    if result is None:
        raise BusiException("会话不存在", status_code=404)
    return result


__all__ = (
    "chat",
    "list_conversation_messages",
    "list_conversations",
    "modify_conversation",
    "page_knowledge_bases",
    "remove_conversation",
)
