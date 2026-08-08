from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from app.core.common.exception import BusiException
from app.core.services.knowledge_base import retrieval as retrieval_service
from app.db.base import DB
from app.db.knowledge_base import mgr as knowledge_base_db
from app.schemas.agent import (
    AgentContext,
    RetrievalToolInput,
    RetrievalToolOutput,
    ToolCall,
    ToolResult,
)

from ..state import KnowledgeHarnessContext


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
        if context.tenant_id is not None and knowledge_base.get("tenant_id") != context.tenant_id:
            raise BusiException("无权访问该知识库", status_code=403)
        if context.access_level == "tenant_member":
            try:
                user_id = int(context.user_id)
            except ValueError:
                raise BusiException("用户上下文无效", status_code=403) from None
            authorized = await knowledge_base_db.guest_get(
                DB.get(),
                int(context.tenant_id),
                user_id,
                context.organization_ids,
                context.kb_id,
            )
            if authorized is None:
                raise BusiException("无权访问该知识库", status_code=403)
        retrieval = await retrieval_service.search(
            context.kb_id,
            payload.query,
            top_k=payload.top_k,
            config=context.qa_config,
            index_version_id=context.index_version_id,
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
    runtime: ToolRuntime[KnowledgeHarnessContext],
) -> dict[str, Any]:
    """检索当前用户有权限访问的知识库内容。"""
    session = runtime.context.session
    call = ToolCall(
        call_id=session.runtime.next_call_id(),
        name="retrieve_knowledge",
        input={"query": query, "top_k": top_k},
    )
    result = await session.runtime.execute(call, session.trusted_context)
    if not result.ok:
        raise BusiException(result.error_message or "知识库检索失败")
    session.store_chunks(result.data.get("chunks", []))
    return result.data


__all__ = ("retrieve_knowledge", "retrieve_knowledge_result")
