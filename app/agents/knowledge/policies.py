"""知识库问答 Agent 的确定性权限与结果安全策略。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.common.exception import BusiException
from app.schemas.agent import AgentContext, AgentResult, ToolCall

if TYPE_CHECKING:
    from app.agents.knowledge.tools.registry import ToolRegistry

READ_ONLY_TOOLS = frozenset({"retrieve_knowledge", "load_conversation_history", "build_citations"})


def authorize_tool(
    *,
    context: AgentContext,
    call: ToolCall,
    registry: ToolRegistry,
) -> None:
    """确认工具已注册且只读，并禁止模型覆盖可信上下文字段。"""
    if call.name not in READ_ONLY_TOOLS or call.name not in registry.names():
        raise BusiException("工具未授权", status_code=403)

    for key in ("kb_id", "user_id", "tenant_id"):
        if key in call.input:
            raise BusiException(f"工具输入不允许覆盖上下文字段: {key}", status_code=403)


def validate_agent_context(task_kb_id: int, task_user_id: str, context: AgentContext) -> None:
    """校验任务标识与 Service 注入的用户、组织及知识库范围一致。"""
    if task_kb_id != context.kb_id or task_user_id != context.user_id:
        raise BusiException("Agent 上下文与问答任务不一致", status_code=403)
    if context.conversation_id is not None and context.conversation_id <= 0:
        raise BusiException("会话上下文无效", status_code=400)
    if any(item <= 0 for item in context.organization_ids) or len(
        set(context.organization_ids)
    ) != len(context.organization_ids):
        raise BusiException("组织授权上下文无效", status_code=403)
    if context.access_level == "tenant_member" and context.tenant_id is None:
        raise BusiException("租户成员上下文缺少租户范围", status_code=403)


def validate_agent_result(result: AgentResult, retrieved_chunks: list[dict]) -> None:
    """确保最终引用全部来自本轮实际检索到的分块。"""
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
