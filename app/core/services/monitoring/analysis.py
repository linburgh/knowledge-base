from __future__ import annotations

from typing import Any

from app.agents.monitoring import MonitoringAgent
from app.core.common import utils
from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.services.platform import audit as audit_service
from app.db.api import check_db_connected
from app.db.base import DB
from app.db.knowledge_base import conversation as conversation_db
from app.db.knowledge_base import conversation_message as message_db
from app.schemas.monitoring import (
    AnalysisConversationModifyRequest,
    AnalysisConversationRequest,
    AnalysisMessageRequest,
    MonitoringContext,
)

from .access import require_monitoring_access, tenant_scope
from .analysis_tools import build_monitoring_tool_registry


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
    from app.core.services.monitoring import mgr as monitoring_service

    time_range = str(payload.context.get("time_range") or "1h")
    requested_scope_key = payload.scope_key or str(payload.context.get("scope_key") or "platform")
    if requested_scope_key not in {"platform", "tenant"}:
        raise BusiException("分析范围必须是 platform 或 tenant")
    scope_key = "tenant" if scope is not None else "platform"
    overview = await monitoring_service.analysis_overview(current_user, time_range, scope_key)
    bound_context = {
        "incident_id": overview.get("incident_id"),
        "scope_key": scope_key,
        "scope_name": overview.get("scope_name"),
        "time_range": time_range,
        "alerts": overview.get("alerts") or [],
        "evidence": overview.get("evidence") or [],
        "tenant_id": scope,
    }
    async with db.transaction():
        conversation_id = await conversation_db.insert_(
            db,
            kb_id=None,
            user_id=current_user.user_id,
            tenant_id=scope,
            conversation_type="monitoring",
            scope_key=scope_key,
            metadata=bound_context,
            title=payload.title or "新建分析会话",
            status="active",
        )
        await audit_service.record(
            db,
            action="monitor_analysis_conversation_created",
            target_type="monitor_analysis_conversation",
            target_id=conversation_id,
            summary={"tenant_id": scope, "incident_id": overview.get("incident_id")},
        )
    return await conversation_db.get(db, id=conversation_id)


@check_db_connected
async def list_conversations(
    current_user: CurrentUser, keyword: str | None = None
) -> list[dict[str, Any]]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    filters = {"conversation_type": "monitoring", "status__ne": "deleted"}
    if scope is not None:
        filters["tenant_id"] = scope
    normalized_keyword = keyword.strip() if keyword and keyword.strip() else None
    return await conversation_db.list(DB.get(), keyword=normalized_keyword, **filters)


@check_db_connected
async def modify_conversation(
    conversation_id: int,
    payload: AnalysisConversationModifyRequest,
    current_user: CurrentUser,
) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    db = DB.get()
    filters = _conversation_filter(conversation_id, scope)
    conversation = await conversation_db.get(db, **filters)
    if conversation is None or conversation.get("status") == "deleted":
        raise BusiException("分析对话不存在", status_code=404)
    title = payload.title.strip()
    if not title:
        raise BusiException("会话名称不能为空")
    async with db.transaction():
        await conversation_db.update_(
            db,
            {"title": title, "updated_at": utils.utc_now()},
            **filters,
        )
        await audit_service.record(
            db,
            action="monitor_analysis_conversation_renamed",
            target_type="monitor_analysis_conversation",
            target_id=conversation_id,
            summary={"tenant_id": scope},
        )
        result = await conversation_db.get(db, **filters)
    if result is None:
        raise BusiException("分析对话不存在", status_code=404)
    return result


@check_db_connected
async def remove_conversation(conversation_id: int, current_user: CurrentUser) -> dict[str, Any]:
    await require_monitoring_access(current_user)
    scope = await tenant_scope(current_user)
    db = DB.get()
    filters = _conversation_filter(conversation_id, scope)
    conversation = await conversation_db.get(db, **filters)
    if conversation is None or conversation.get("status") == "deleted":
        raise BusiException("分析对话不存在", status_code=404)
    async with db.transaction():
        await conversation_db.update_(
            db,
            {"status": "deleted", "updated_at": utils.utc_now()},
            **filters,
        )
        await audit_service.record(
            db,
            action="monitor_analysis_conversation_deleted",
            target_type="monitor_analysis_conversation",
            target_id=conversation_id,
            summary={"tenant_id": scope},
        )
        result = await conversation_db.get(db, **filters)
    if result is None:
        raise BusiException("分析对话不存在", status_code=404)
    return result


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
    scope_key = "tenant" if scope is not None else "platform"
    conversation_context = conversation.get("metadata") or {}
    conversation_messages = await message_db.list(db, conversation_id=conversation_id)
    prior_fact_set: dict[str, Any] = {}
    for message in reversed(conversation_messages):
        if message.get("role") != "assistant":
            continue
        metadata = message.get("metadata") or {}
        candidate = metadata.get("fact_set")
        if isinstance(candidate, dict) and candidate.get("sources"):
            prior_fact_set = candidate
            break
    agent = MonitoringAgent(tools=build_monitoring_tool_registry(scope=scope))
    context = {
        **conversation_context,
        "time_range": str(conversation_context.get("time_range") or "1h"),
        "scope_key": scope_key,
        "scope_name": conversation_context.get("scope_name"),
        "tenant_id": scope,
        "user_id": current_user.user_id,
        "role": "tenant_admin" if scope is not None else "platform_super_admin",
        # 只接受同一授权会话中由服务端持久化的事实集合，忽略客户端覆盖值。
        "prior_fact_set": prior_fact_set,
    }
    async with db.transaction():
        user_message_id = await message_db.insert_(
            db,
            conversation_id=conversation_id,
            kb_id=None,
            user_id=current_user.user_id,
            role="user",
            content=payload.content,
            metadata={
                "scope_key": scope_key,
            },
        )
    try:
        result = await agent.analyze(
            question=payload.content,
            context=MonitoringContext.model_validate(context),
        )
    except Exception as exc:
        result = {
            "answer": (
                "> **本次分析暂不可用。**\n\n"
                "- 时间口径：当前会话约定范围，中国标准时间。\n"
                "- 原始告警和证据仍可查询。\n\n"
                "### 后续建议\n\n"
                "1. 请稍后重新发起分析。\n"
                "2. 如需立即核查，请直接查看原始告警和证据明细。"
            ),
            "agent": "自主监控智能体",
            "evidence": [],
            "status": "failed",
            "intent": "period_review",
            "conclusion": "unknown",
            "data_status": "failed",
            "time_range": {
                "label": str(context.get("time_range") or "最近1小时"),
                "timezone": "Asia/Shanghai",
            },
            "scope": {
                "type": str(context.get("scope_key") or "platform"),
                "name": str(context.get("scope_name") or "当前授权范围"),
            },
            "limitations": ["自主监控智能体执行失败"],
            "tool_calls": [],
            "planning": {
                "mode": "failed",
                "goal": "分析授权范围内的监控运行事实",
                "uncertainties": ["自主监控智能体执行失败"],
                "error": type(exc).__name__,
            },
            "answering": {"mode": "fallback", "error": type(exc).__name__},
            "error": type(exc).__name__,
            "fact_set": {},
        }
    incident_id = (
        conversation_context.get("incident_id")
        if (result.get("time_range") or {}).get("source") == "conversation"
        else None
    )
    async with db.transaction():
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
                "incident_id": incident_id,
                "intent": result.get("intent"),
                "conclusion": result.get("conclusion"),
                "data_status": result.get("data_status"),
                "time_range": result.get("time_range"),
                "scope": result.get("scope"),
                "limitations": result.get("limitations") or [],
                "tool_calls": result.get("tool_calls") or [],
                "planning": result.get("planning") or {},
                "answering": result.get("answering") or {},
                "fact_set": result.get("fact_set") or {},
            },
        )
        await conversation_db.update_(db, {"updated_at": utils.utc_now()}, id=conversation_id)
        await audit_service.record(
            db,
            action="monitor_analysis_message_sent",
            target_type="monitor_analysis_conversation",
            target_id=conversation_id,
            result="success" if result["status"] == "completed" else "failed",
            summary={
                "tenant_id": scope,
                "incident_id": incident_id,
                "evidence_count": len(result.get("evidence") or []),
                "intent": result.get("intent"),
                "conclusion": result.get("conclusion"),
                "tool_call_count": len(result.get("tool_calls") or []),
                "planning_mode": (result.get("planning") or {}).get("mode"),
                "answering_mode": (result.get("answering") or {}).get("mode"),
            },
        )
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
