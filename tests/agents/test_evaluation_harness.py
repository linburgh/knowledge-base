from __future__ import annotations

import pytest

from app.agents.evaluation.agent import EvaluationAgent
from app.agents.evaluation.policies import authorize_evaluation_tool
from app.agents.evaluation.tools.registry import EvaluationToolRegistry
from app.core.common.exception import BusiException
from app.schemas.agent import AgentResult
from app.schemas.evaluation import (
    EvaluationAgentContext,
    EvaluationAgentTask,
    KnowledgeAgentCallResult,
)


def _context(**overrides) -> EvaluationAgentContext:
    values = {
        "run_id": 1,
        "task_id": 2,
        "user_id": "3",
        "tenant_id": 4,
        "organization_ids": [5],
        "kb_id": 6,
        "index_version_id": 7,
        "qa_config": {"retrieval": {"top_k": 3}},
        "is_super_admin": True,
    }
    values.update(overrides)
    return EvaluationAgentContext(**values)


@pytest.mark.asyncio
async def test_evaluation_production_entry_runs_langgraph_and_registry() -> None:
    calls = []
    registry = EvaluationToolRegistry()

    async def handler(payload, context):
        calls.append((payload, context))
        return KnowledgeAgentCallResult(
            result=AgentResult(
                answer="答案",
                mode="single_retrieval",
                status="completed",
                top_k=3,
                hit_count=1,
                termination_reason="completed",
                duration_ms=1,
            )
        )

    registry.register("call_knowledge_agent", handler)
    result = await EvaluationAgent(registry=registry).run(
        EvaluationAgentTask(
            config={
                "kb_id": 6,
                "user_id": 3,
                "questions_source": "generated",
                "business_scope_source": "description",
                "business_description": "业务范围",
            },
            questions=[{"question": "问题", "source": "generated"}],
        ),
        _context(),
    )
    assert result.summary.status == "completed"
    assert result.summary.termination_reason == "completed"
    assert result.summary.tool_calls[0].name == "call_knowledge_agent"
    assert result.summary.skill_refs[0].name == "evaluation"
    assert result.report["dataset"]["total"] == 1
    assert len(calls) == 1
    assert calls[0][1].organization_ids == [5]


def test_evaluation_tool_rejects_trusted_field_override() -> None:
    with pytest.raises(BusiException, match="不允许覆盖可信字段"):
        authorize_evaluation_tool(
            name="call_knowledge_agent",
            payload={"question": "问题", "kb_id": 999},
            context=_context(),
            registered_tools=frozenset({"call_knowledge_agent"}),
        )


@pytest.mark.asyncio
async def test_evaluation_entry_rejects_unprivileged_context() -> None:
    task = EvaluationAgentTask(
        config={
            "kb_id": 6,
            "user_id": 3,
            "questions_source": "generated",
            "business_scope_source": "description",
            "business_description": "业务范围",
        },
        questions=[{"question": "问题", "source": "generated"}],
    )
    with pytest.raises(BusiException, match="无权操作自主评测"):
        await EvaluationAgent().run(task, _context(is_super_admin=False))


@pytest.mark.asyncio
async def test_evaluation_cancellation_stops_before_tool_execution() -> None:
    calls = 0
    registry = EvaluationToolRegistry()

    async def handler(payload, context):
        nonlocal calls
        del payload, context
        calls += 1
        raise AssertionError("取消后不应执行工具")

    async def cancelled():
        return True

    registry.register("call_knowledge_agent", handler)
    result = await EvaluationAgent(registry=registry, cancel_check=cancelled).run(
        EvaluationAgentTask(
            config={
                "kb_id": 6,
                "user_id": 3,
                "questions_source": "generated",
                "business_scope_source": "description",
                "business_description": "业务范围",
            },
            questions=[{"question": "问题", "source": "generated"}],
        ),
        _context(),
    )
    assert result.summary.status == "cancelled"
    assert result.summary.termination_reason == "cancelled"
    assert result.report == {}
    assert calls == 0
