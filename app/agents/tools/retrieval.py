from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from app.agents.policies import authorize_tool
from app.core.common.exception import BusiException
from app.core.services import retrieval as retrieval_service
from app.db import knowledge_base as knowledge_base_db
from app.db.base import DB
from app.schemas.agent import (
    AgentContext,
    RetrievalToolInput,
    RetrievalToolOutput,
    ToolCall,
    ToolResult,
)


async def retrieve_knowledge_result(call: ToolCall, context: AgentContext) -> ToolResult:
    try:
        payload = RetrievalToolInput.model_validate(call.input)
    except ValueError as exc:
        return ToolResult(
            call_id=call.call_id,
            name="retrieve_knowledge",
            ok=False,
            error_code="INVALID_INPUT",
            error_message=str(exc),
        )

    try:
        knowledge_base = await knowledge_base_db.get(DB.get(), id=context.kb_id)
        if knowledge_base is None or knowledge_base.get("status") == "deleted":
            raise BusiException("知识库不存在", status_code=404)
        retrieval = await retrieval_service.search(
            context.kb_id,
            payload.query,
            top_k=payload.top_k,
        )
    except BusiException as exc:
        return ToolResult(
            call_id=call.call_id,
            name="retrieve_knowledge",
            ok=False,
            error_code="RETRIEVAL_FAILED",
            error_message=exc.message,
        )
    except Exception:
        return ToolResult(
            call_id=call.call_id,
            name="retrieve_knowledge",
            ok=False,
            error_code="RETRIEVAL_FAILED",
            error_message="知识库检索失败",
        )

    output = RetrievalToolOutput(
        kb_id=retrieval.kb_id,
        query=retrieval.query,
        mode=retrieval.mode,
        top_k=retrieval.top_k,
        chunks=[chunk.model_dump() for chunk in retrieval.chunks],
    )
    return ToolResult(
        call_id=call.call_id,
        name="retrieve_knowledge",
        ok=True,
        data=output.model_dump(),
        hit_count=len(output.chunks),
    )


@tool
async def retrieve_knowledge(
    query: str,
    top_k: int | None = None,
    *,
    runtime: ToolRuntime[AgentContext],
) -> dict[str, Any]:
    """检索当前用户有权限访问的知识库内容。"""
    call = ToolCall(
        call_id=f"model-retrieve-{runtime.state.get('agent_step', 0)}",
        name="retrieve_knowledge",
        input={"query": query, "top_k": top_k},
    )
    from .registry import build_default_registry

    authorize_tool(context=runtime.context, call=call, registry=build_default_registry())
    result = await retrieve_knowledge_result(
        call,
        runtime.context,
    )
    if not result.ok:
        raise BusiException(result.error_message or "知识库检索失败")
    return result.data


__all__ = ("retrieve_knowledge", "retrieve_knowledge_result")
