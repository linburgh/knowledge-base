from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from app.agents.knowledge.policies import authorize_tool
from app.schemas.agent import (
    AgentContext,
    CitationCandidate,
    CitationToolInput,
    CitationToolOutput,
    ToolCall,
    ToolResult,
)


def _build_candidates(chunks: list[dict[str, Any]]) -> CitationToolOutput:
    candidates: list[CitationCandidate] = []
    seen: set[int] = set()
    for chunk in chunks:
        chunk_id = chunk.get("id")
        if chunk_id is None or int(chunk_id) in seen:
            continue
        seen.add(int(chunk_id))
        candidates.append(
            CitationCandidate(
                document_id=int(chunk["document_id"]),
                chunk_id=int(chunk_id),
                source_name=str(chunk.get("source_name") or "未知来源"),
                page=chunk.get("page"),
                snippet=str(chunk.get("content") or ""),
                score=chunk.get("score"),
                rank=len(candidates) + 1,
            )
        )
    return CitationToolOutput(citations=candidates)


def validate_citations(
    citations: list[CitationCandidate],
    chunks: list[dict[str, Any]],
) -> None:
    allowed = {int(chunk["id"]) for chunk in chunks if chunk.get("id") is not None}
    if any(citation.chunk_id not in allowed for citation in citations):
        raise ValueError("引用必须来自本次检索结果")


async def build_citations_result(call: ToolCall, context: AgentContext) -> ToolResult:
    del context
    try:
        payload = CitationToolInput.model_validate(call.input)
        output = _build_candidates(payload.chunks)
    except (TypeError, ValueError, KeyError) as exc:
        return ToolResult(
            call_id=call.call_id,
            name="build_citations",
            ok=False,
            error_code="INVALID_CITATIONS",
            error_message=str(exc),
        )
    return ToolResult(
        call_id=call.call_id,
        name="build_citations",
        ok=True,
        data=output.model_dump(),
        hit_count=len(output.citations),
    )


@tool
async def build_citations(
    chunks: list[dict[str, Any]],
    *,
    runtime: ToolRuntime[AgentContext],
) -> dict[str, Any]:
    """整理本次真实检索结果中的引用。"""
    call = ToolCall(
        call_id=f"model-citations-{runtime.state.get('agent_step', 0)}",
        name="build_citations",
        input={"chunks": chunks},
    )
    from .registry import build_default_registry

    authorize_tool(context=runtime.context, call=call, registry=build_default_registry())
    result = await build_citations_result(
        call,
        runtime.context,
    )
    if not result.ok:
        raise ValueError(result.error_message or "引用整理失败")
    return result.data


__all__ = ("build_citations", "build_citations_result", "validate_citations")
