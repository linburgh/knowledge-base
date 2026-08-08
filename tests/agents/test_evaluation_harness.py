from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.evaluation.agent import (
    EXCLUDED_BUILTIN_TOOLS,
    EvaluationAgent,
    build_evaluation_deep_agent,
)
from app.agents.evaluation.models import EvaluationAgentOutput, EvaluationConfig
from app.agents.evaluation.policies import authorize_evaluation_tool
from app.agents.evaluation.tools import (
    execute_evaluation_cases,
    inspect_evaluation_results,
    retry_evaluation_cases,
)
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


def _task(*questions: str, **config_overrides) -> EvaluationAgentTask:
    config = {
        "kb_id": 6,
        "user_id": 3,
        "questions_source": "generated",
        "business_scope_source": "description",
        "business_description": "业务范围",
    }
    config.update(config_overrides)
    return EvaluationAgentTask(
        config=config,
        questions=[{"question": question, "source": "generated"} for question in questions],
    )


class FakeDeepAgent:
    def __init__(self, *, retry_case_numbers: list[int] | None = None) -> None:
        self.retry_case_numbers = retry_case_numbers or []
        self.inputs = []
        self.contexts = []

    async def ainvoke(self, inputs, *, context, config):
        self.inputs.append((inputs, config))
        self.contexts.append(context)
        runtime = SimpleNamespace(context=context)
        await execute_evaluation_cases.coroutine(runtime=runtime)
        if self.retry_case_numbers:
            await retry_evaluation_cases.coroutine(
                self.retry_case_numbers,
                runtime=runtime,
            )
        inspected = await inspect_evaluation_results.coroutine(runtime=runtime)
        output = EvaluationAgentOutput(
            goal="验证知识库问答质量",
            rationale="已执行全部问题并检查确定性指标",
            findings=[f"当前成功率为 {inspected['metrics']['metrics']['success_rate']['value']}"],
            recommendations=["持续观察异常样品"],
            confidence=0.9,
        )
        return {
            "structured_response": output,
            "messages": [
                AIMessage(content="调用评测工具"),
                ToolMessage(
                    content="执行完成",
                    tool_call_id="execute-1",
                    name="execute_evaluation_cases",
                ),
                AIMessage(content="形成结构化结果"),
            ],
        }


def test_build_evaluation_agent_uses_restricted_deepagents_harness() -> None:
    config = EvaluationConfig(
        kb_id=6,
        user_id=3,
        questions_source="generated",
        business_scope_source="description",
        business_description="业务范围",
        retry_count=1,
    )
    compiled = object()
    with patch(
        "app.agents.evaluation.agent.create_deep_agent",
        return_value=compiled,
    ) as create:
        result = build_evaluation_deep_agent(config, model=object())

    assert result is compiled
    kwargs = create.call_args.kwargs
    assert kwargs["name"] == "evaluation_agent"
    assert kwargs["skills"] == ["/skills/"]
    assert kwargs["subagents"] == []
    assert kwargs["context_schema"].__name__ == "EvaluationHarnessContext"
    assert {tool.name for tool in kwargs["tools"]} == {
        "execute_evaluation_cases",
        "inspect_evaluation_results",
        "retry_evaluation_cases",
    }
    middleware_types = {type(item) for item in kwargs["middleware"]}
    assert middleware_types == {
        ModelCallLimitMiddleware,
        ModelRetryMiddleware,
        ToolCallLimitMiddleware,
        ToolRetryMiddleware,
    }
    assert isinstance(kwargs["response_format"], ToolStrategy)
    assert "conclusion" not in EvaluationAgentOutput.model_fields
    assert kwargs["permissions"][0].mode == "allow"
    assert kwargs["permissions"][0].paths == ["/skills/**"]
    assert kwargs["permissions"][1].mode == "deny"
    assert kwargs["permissions"][1].paths == ["/**"]
    assert {"write_todos", "write_file", "execute", "task"}.issubset(EXCLUDED_BUILTIN_TOOLS)


@pytest.mark.asyncio
async def test_evaluation_production_entry_runs_deep_agent_and_registry() -> None:
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
    deep_agent = FakeDeepAgent()
    result = await EvaluationAgent(
        registry=registry,
        agent_factory=lambda config: deep_agent,
    ).run(_task("问题"), _context())

    assert result.summary.status == "completed"
    assert result.summary.model_call_count == 2
    assert result.summary.skill_refs[0].name == "analysis"
    assert result.report["agent_analysis"]["goal"] == "验证知识库问答质量"
    assert result.report["dataset"]["total"] == 1
    assert calls[0][1].organization_ids == [5]
    assert deep_agent.contexts[0].session.trusted_context.tenant_id == 4
    assert "/skills/analysis/SKILL.md" in deep_agent.inputs[0][0]["files"]


def test_tool_runtime_context_is_not_exposed_as_model_argument() -> None:
    assert "runtime" not in execute_evaluation_cases.tool_call_schema.model_fields
    assert "runtime" not in retry_evaluation_cases.tool_call_schema.model_fields
    assert "runtime" not in inspect_evaluation_results.tool_call_schema.model_fields
    assert not execute_evaluation_cases.tool_call_schema.model_fields
    assert set(retry_evaluation_cases.tool_call_schema.model_fields) == {"case_numbers"}


def test_evaluation_tool_rejects_trusted_field_override() -> None:
    with pytest.raises(BusiException, match="不允许覆盖可信字段"):
        authorize_evaluation_tool(
            name="call_knowledge_agent",
            payload={"question": "问题", "kb_id": 999},
            context=_context(),
            registered_tools=frozenset({"call_knowledge_agent"}),
        )


@pytest.mark.asyncio
async def test_evaluation_entry_rejects_unprivileged_context_before_agent_creation() -> None:
    factory_called = False

    def factory(config):
        nonlocal factory_called
        del config
        factory_called = True
        return FakeDeepAgent()

    with pytest.raises(BusiException, match="无权操作自主评测"):
        await EvaluationAgent(agent_factory=factory).run(
            _task("问题"),
            _context(is_super_admin=False),
        )
    assert factory_called is False


@pytest.mark.asyncio
async def test_evaluation_cancellation_stops_before_knowledge_agent() -> None:
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
    result = await EvaluationAgent(
        registry=registry,
        cancel_check=cancelled,
        agent_factory=lambda config: FakeDeepAgent(),
    ).run(_task("问题"), _context())

    assert result.summary.status == "cancelled"
    assert result.report == {}
    assert calls == 0


@pytest.mark.asyncio
async def test_deep_agent_retries_only_selected_case() -> None:
    calls = []
    registry = EvaluationToolRegistry()

    async def handler(payload, context):
        del context
        calls.append(payload["case_no"])
        attempt = calls.count(payload["case_no"])
        fallback = payload["case_no"] == 2 and attempt == 1
        return KnowledgeAgentCallResult(
            result=AgentResult(
                answer="资料不足" if fallback else "答案",
                mode="single_retrieval",
                status="completed",
                top_k=3,
                hit_count=0 if fallback else 1,
                termination_reason="fallback" if fallback else "completed",
                duration_ms=1,
            )
        )

    registry.register("call_knowledge_agent", handler)
    result = await EvaluationAgent(
        registry=registry,
        agent_factory=lambda config: FakeDeepAgent(retry_case_numbers=[2]),
    ).run(_task("问题一", "问题二", max_review_rounds=1), _context())

    assert calls == [1, 2, 2]
    assert result.case_results[1]["metadata"]["review_round"] == 1
    assert result.report["agent_analysis"]["reviewed_case_numbers"] == [2]


@pytest.mark.asyncio
async def test_deep_agent_cannot_exceed_review_limit() -> None:
    registry = EvaluationToolRegistry()

    async def handler(payload, context):
        del payload, context
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
    with pytest.raises(BusiException, match="最大复核轮次"):
        await EvaluationAgent(
            registry=registry,
            agent_factory=lambda config: FakeDeepAgent(retry_case_numbers=[1]),
        ).run(_task("问题", max_review_rounds=0), _context())
