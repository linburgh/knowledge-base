from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from app.agents.knowledge.policies import authorize_tool
from app.db import conversation as conversation_db
from app.db import conversation_message as conversation_message_db
from app.db.base import DB
from app.schemas.agent import (
    AgentContext,
    HistoryToolInput,
    HistoryToolOutput,
    ToolCall,
    ToolResult,
)

MAX_MESSAGE_CHARS = 4000
MAX_HISTORY_CHARS = 12000
STATUS_DELETED = "deleted"


def _history_payload(rows: list[dict[str, Any]], context: AgentContext) -> HistoryToolOutput:
    messages: list[dict[str, Any]] = []
    total_chars = 0
    for row in rows[-50:]:
        content = str(row.get("content") or "")[:MAX_MESSAGE_CHARS]
        if total_chars + len(content) > MAX_HISTORY_CHARS:
            break
        messages.append(
            {
                "role": row.get("role"),
                "content": content,
                "created_at": row.get("created_at").isoformat()
                if row.get("created_at") is not None
                else None,
            }
        )
        total_chars += len(content)
    return HistoryToolOutput(
        conversation_id=context.conversation_id,
        messages=messages,
    )


async def load_conversation_history_result(
    call: ToolCall,
    context: AgentContext,
) -> ToolResult:
    try:
        payload = HistoryToolInput.model_validate(call.input or {})
    except ValueError as exc:
        return ToolResult(
            call_id=call.call_id,
            name="load_conversation_history",
            ok=False,
            error_code="INVALID_INPUT",
            error_message=str(exc),
        )
    if context.conversation_id is None:
        output = HistoryToolOutput(conversation_id=None, messages=[])
        return ToolResult(
            call_id=call.call_id,
            name="load_conversation_history",
            ok=True,
            data=output.model_dump(),
        )

    db = DB.get()
    conversation = await conversation_db.get(db, id=context.conversation_id)
    if (
        conversation is None
        or conversation.get("status") == STATUS_DELETED
        or conversation.get("kb_id") != context.kb_id
        or str(conversation.get("user_id")) != context.user_id
    ):
        return ToolResult(
            call_id=call.call_id,
            name="load_conversation_history",
            ok=False,
            error_code="CONVERSATION_DENIED",
            error_message="会话不存在或无权访问",
        )

    rows = await conversation_message_db.list(db, conversation_id=context.conversation_id)
    output = _history_payload(rows[-payload.limit :], context)
    return ToolResult(
        call_id=call.call_id,
        name="load_conversation_history",
        ok=True,
        data=output.model_dump(),
        hit_count=len(output.messages),
    )


@tool
async def load_conversation_history(
    limit: int = 10,
    *,
    runtime: ToolRuntime[AgentContext],
) -> dict[str, Any]:
    """读取当前用户当前知识库会话的有限历史。"""
    call = ToolCall(
        call_id=f"model-history-{runtime.state.get('agent_step', 0)}",
        name="load_conversation_history",
        input={"limit": limit},
    )
    from .registry import build_default_registry

    authorize_tool(context=runtime.context, call=call, registry=build_default_registry())
    result = await load_conversation_history_result(
        call,
        runtime.context,
    )
    if not result.ok:
        raise PermissionError(result.error_message or "会话历史不可用")
    return result.data


__all__ = ("load_conversation_history", "load_conversation_history_result")
