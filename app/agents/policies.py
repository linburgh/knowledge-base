from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.common.exception import BusiException
from app.schemas.agent import AgentContext, AgentResult, ToolCall

if TYPE_CHECKING:
    from app.agents.tools.registry import ToolRegistry

READ_ONLY_TOOLS = frozenset({"retrieve_knowledge", "load_conversation_history", "build_citations"})


def authorize_tool(
    *,
    context: AgentContext,
    call: ToolCall,
    registry: ToolRegistry,
) -> None:
    if call.name not in READ_ONLY_TOOLS or call.name not in registry.names():
        raise BusiException("工具未授权", status_code=403)

    for key in ("kb_id", "user_id", "tenant_id"):
        if key in call.input:
            raise BusiException(f"工具输入不允许覆盖上下文字段: {key}", status_code=403)


def validate_agent_context(task_kb_id: int, task_user_id: str, context: AgentContext) -> None:
    if task_kb_id != context.kb_id or task_user_id != context.user_id:
        raise BusiException("Agent 上下文与问答任务不一致", status_code=403)
    if context.conversation_id is not None and context.conversation_id <= 0:
        raise BusiException("会话上下文无效", status_code=400)


def validate_agent_result(result: AgentResult, retrieved_chunks: list[dict]) -> None:
    allowed = {int(chunk["id"]) for chunk in retrieved_chunks if chunk.get("id") is not None}
    for citation in result.citations:
        if citation.chunk_id not in allowed:
            raise BusiException("引用不属于本次检索结果", status_code=500)


__all__ = (
    "READ_ONLY_TOOLS",
    "authorize_tool",
    "validate_agent_context",
    "validate_agent_result",
)
