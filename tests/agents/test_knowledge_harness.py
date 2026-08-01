from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.knowledge.agent import _select_citations, _skill_refs, run_knowledge_agent
from app.agents.knowledge.runtime import AgentOutputInvalid, AgentRuntime
from app.agents.knowledge.tools.registry import ToolRegistry, build_default_registry
from app.agents.knowledge.tools.retrieval import retrieve_knowledge_result
from app.schemas.agent import AgentContext, AgentTask, ToolCall, ToolResult


def test_knowledge_skills_have_versioned_runtime_references() -> None:
    refs = _skill_refs()
    assert {item.name for item in refs} == {"query-analysis", "answer-writing"}
    assert all(len(item.version) == 12 for item in refs)


@pytest.mark.asyncio
async def test_invalid_citation_id_is_rejected_before_citation_tool() -> None:
    runtime = AgentRuntime(
        registry=build_default_registry(),
        max_steps=4,
        max_tool_calls=4,
        tool_timeout_seconds=1,
    )
    with pytest.raises(AgentOutputInvalid, match="检索结果之外"):
        await _select_citations(
            [{"id": 1, "document_id": 2, "content": "资料"}],
            [999],
            AgentContext(kb_id=1, user_id="2"),
            runtime,
        )
    assert runtime.tool_call_count == 0


@pytest.mark.asyncio
async def test_retrieval_rejects_cross_tenant_before_search(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.knowledge.tools.retrieval.knowledge_base_db.get",
        AsyncMock(return_value={"id": 1, "tenant_id": 8, "status": "active"}),
    )
    search = AsyncMock()
    monkeypatch.setattr("app.agents.knowledge.tools.retrieval.retrieval_service.search", search)
    result = await retrieve_knowledge_result(
        ToolCall(
            call_id="cross-tenant",
            name="retrieve_knowledge",
            input={"query": "测试"},
        ),
        AgentContext(kb_id=1, user_id="2", tenant_id=7, access_level="tenant_member"),
    )
    assert result.ok is False
    assert result.error_code == "RETRIEVAL_FAILED"
    search.assert_not_awaited()


def test_knowledge_registry_declares_read_only_schemas() -> None:
    registry = build_default_registry()
    assert registry.names() == {
        "retrieve_knowledge",
        "load_conversation_history",
        "build_citations",
    }
    assert all(registry.definition(name).read_only for name in registry.names())
    assert all(registry.definition(name).input_schema is not dict for name in registry.names())


@pytest.mark.asyncio
async def test_simple_question_uses_runtime_registry_model_and_skills(monkeypatch) -> None:
    registry = ToolRegistry()

    async def retrieve(call, context):
        del context
        return ToolResult(
            call_id=call.call_id,
            name="retrieve_knowledge",
            ok=True,
            data={
                "chunks": [
                    {
                        "id": 10,
                        "document_id": 20,
                        "content": "报销需要发票。",
                        "source_name": "报销制度",
                    }
                ]
            },
            hit_count=1,
        )

    async def history(call, context):
        del context
        return ToolResult(call_id=call.call_id, name="load_conversation_history", ok=True)

    async def citations(call, context):
        del context
        chunk = call.input["chunks"][0]
        return ToolResult(
            call_id=call.call_id,
            name="build_citations",
            ok=True,
            data={
                "citations": [
                    {
                        "document_id": chunk["document_id"],
                        "chunk_id": chunk["id"],
                        "source_name": chunk["source_name"],
                        "snippet": chunk["content"],
                        "rank": 1,
                    }
                ]
            },
            hit_count=1,
        )

    registry.register("retrieve_knowledge", retrieve)
    registry.register("load_conversation_history", history)
    registry.register("build_citations", citations)

    class Model:
        async def ainvoke(self, messages):
            assert "query-analysis" in messages[1]["content"]
            return {"answer": "报销需要提供发票。", "citation_chunk_ids": [10]}

    monkeypatch.setattr("app.agents.knowledge.agent.build_default_registry", lambda: registry)
    monkeypatch.setattr("app.agents.knowledge.agent.get_knowledge_answer_model", lambda: Model())
    monkeypatch.setattr(
        "app.agents.knowledge.agent.CONF",
        SimpleNamespace(
            agent=SimpleNamespace(
                enabled=True,
                max_steps=4,
                max_tool_calls=6,
                tool_timeout_seconds=1,
                max_retries=0,
                total_timeout_seconds=5,
            ),
            chat=SimpleNamespace(model="test-model"),
        ),
    )
    monkeypatch.setattr(
        "app.agents.knowledge.agent.emit_gather_event",
        AsyncMock(return_value=None),
    )
    target = run_knowledge_agent
    while hasattr(target, "__wrapped__"):
        target = target.__wrapped__
    result = await target(
        AgentTask(kb_id=1, question="报销需要什么？", user_id="2"),
        AgentContext(kb_id=1, user_id="2"),
    )
    assert result.status == "completed"
    assert result.tool_call_count == 2
    assert result.model_call_count == 1
    assert [item.name for item in result.skill_refs] == ["query-analysis", "answer-writing"]
    assert result.citations[0].chunk_id == 10


def test_deep_agent_is_configured_with_real_read_only_tools() -> None:
    source = inspect.getsource(
        __import__("app.agents.knowledge.agent", fromlist=["get_knowledge_agent"])
        .get_knowledge_agent
    )
    assert "tools=[retrieve_knowledge, load_conversation_history, build_citations]" in source
