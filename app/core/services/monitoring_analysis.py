from __future__ import annotations

from typing import Any

from app.agents.monitoring import MonitoringAgent
from app.core.common import utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.db import conversation as conversation_db
from app.db import conversation_message as message_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.schemas.monitoring import AnalysisConversationRequest, AnalysisMessageRequest

from .monitoring_access import require_monitoring_access, tenant_scope


def _conversation_filter(conversation_id: int, scope: int | None) -> dict[str, Any]:
    filters: dict[str, Any] = {"id": conversation_id, "conversation_type": "monitoring"}
    if scope is not None:
        filters["tenant_id"] = scope
    return filters


@check_db_connected
async def create_conversation(
    payload: AnalysisConversationRequest, current_user: CurrentUser
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    db = DB.get()
    async with db.transaction():
        conversation_id = await conversation_db.insert_(
            db,
            kb_id=None,
            user_id=current_user.user_id,
            tenant_id=scope,
            conversation_type="monitoring",
            scope_key=payload.scope_key,
            metadata=payload.context,
            title=payload.title or "监控分析对话",
            status="active",
        )
    return await conversation_db.get(db, id=conversation_id)


@check_db_connected
async def list_conversations(current_user: CurrentUser) -> list[dict[str, Any]]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    filters = {"conversation_type": "monitoring"}
    if scope is not None:
        filters["tenant_id"] = scope
    return await conversation_db.list(DB.get(), **filters)


@check_db_connected
async def send_message(
    conversation_id: int, payload: AnalysisMessageRequest, current_user: CurrentUser
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    db = DB.get()
    conversation = await conversation_db.get(db, **_conversation_filter(conversation_id, scope))
    if conversation is None:
        raise BusiException("分析对话不存在", status_code=404)
    agent = MonitoringAgent()
    context = {
        **(conversation.get("metadata") or {}),
        **payload.context,
        "role": "tenant_admin" if scope is not None else "platform_super_admin",
    }
    async with db.transaction():
        user_message_id = await message_db.insert_(
            db,
            conversation_id=conversation_id,
            kb_id=None,
            user_id=current_user.user_id,
            role="user",
            content=payload.content,
            metadata=payload.context,
        )
        result = await agent.analyze(question=payload.content, context=context)
        answer_id = await message_db.insert_(
            db,
            conversation_id=conversation_id,
            kb_id=None,
            user_id=current_user.user_id,
            role="assistant",
            content=result["answer"],
            metadata={
                "agent": result["agent"],
                "evidence": result["evidence"],
                "status": result["status"],
            },
        )
        await conversation_db.update_(db, {"updated_at": utils.utc_now()}, id=conversation_id)
    return {
        "conversation_id": conversation_id,
        "user_message_id": user_message_id,
        "message_id": answer_id,
        **result,
    }


@check_db_connected
async def messages(conversation_id: int, current_user: CurrentUser) -> list[dict[str, Any]]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    if await conversation_db.get(DB.get(), **_conversation_filter(conversation_id, scope)) is None:
        raise BusiException("分析对话不存在", status_code=404)
    return await message_db.list(DB.get(), conversation_id=conversation_id)
