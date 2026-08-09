from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.monitoring.agent import (
    EXCLUDED_BUILTIN_TOOLS,
    MonitoringAgent,
    build_monitoring_deep_agent,
)
from app.agents.monitoring.models import MonitoringAgentOutput
from app.agents.monitoring.runtime import (
    MonitoringModelCallAccountingMiddleware,
    MonitoringRuntime,
)
from app.agents.monitoring.skills import load_skill
from app.agents.monitoring.state import MonitoringSession
from app.agents.monitoring.tools import MONITORING_ANALYSIS_TOOLS
from app.agents.monitoring.tools.registry import MonitoringToolRegistry
from app.core.common.structured_output import StructuredOutputRepairResult


def _window() -> tuple[datetime, datetime]:
    timezone = ZoneInfo("Asia/Shanghai")
    end = datetime.now(timezone).replace(second=0, microsecond=0)
    return end - timedelta(hours=1), end


class FakeMonitoringDeepAgent:
    async def ainvoke(self, inputs, *, context, config):
        del inputs, config
        runtime = SimpleNamespace(context=context)
        for monitoring_tool in MONITORING_ANALYSIS_TOOLS[:5]:
            await monitoring_tool.coroutine(runtime=runtime)
        return {
            "structured_response": MonitoringAgentOutput(
                intent="platform_health",
                goal="判断平台运行状态",
                answer_markdown="已根据中国标准时间内的授权监控事实完成分析。",
                conclusion_ack="normal",
                layout_reason="事实较少，使用简短结论",
                confidence=0.9,
            ),
            "messages": [
                AIMessage(content="调用监控工具"),
                ToolMessage(
                    content="完成",
                    tool_call_id="monitor-1",
                    name="query_health_snapshots",
                ),
                AIMessage(content="返回结构化分析"),
            ],
        }


class UnstructuredMonitoringDeepAgent:
    async def ainvoke(self, inputs, *, context, config):
        del inputs, config
        runtime = SimpleNamespace(context=context)
        tool = next(item for item in MONITORING_ANALYSIS_TOOLS if item.name == "query_alerts")
        await tool.coroutine(runtime=runtime)
        return {"messages": [AIMessage(content="已根据中国标准时间的授权监控事实完成分析。")]}


class SlowFinalMonitoringDeepAgent:
    async def ainvoke(self, inputs, *, context, config):
        del inputs, config
        runtime = SimpleNamespace(context=context)
        tool = next(item for item in MONITORING_ANALYSIS_TOOLS if item.name == "query_alerts")
        await tool.coroutine(runtime=runtime)
        # 模拟已查询真实事实，但模型供应商迟迟不返回最终结构化结果。
        await asyncio.sleep(1)


class MultiSourceSlowFinalMonitoringDeepAgent:
    async def ainvoke(self, inputs, *, context, config):
        del inputs, config
        runtime = SimpleNamespace(context=context)
        for name in ("query_alerts", "query_health_snapshots"):
            tool = next(item for item in MONITORING_ANALYSIS_TOOLS if item.name == name)
            await tool.coroutine(runtime=runtime)
        await asyncio.sleep(1)


class ProviderFailureMonitoringDeepAgent:
    async def ainvoke(self, inputs, *, context, config):
        del inputs, config
        runtime = SimpleNamespace(context=context)
        tool = next(item for item in MONITORING_ANALYSIS_TOOLS if item.name == "query_alerts")
        await tool.coroutine(runtime=runtime)
        raise RuntimeError("provider unavailable")


class NoToolProviderFailureMonitoringDeepAgent:
    async def ainvoke(self, inputs, *, context, config):
        del inputs, context, config
        raise RuntimeError("provider unavailable")


async def _unavailable_repair(**kwargs):
    del kwargs
    return StructuredOutputRepairResult(
        value=None,
        attempted=True,
        error="StructuredOutputMissing",
    )


def test_monitoring_skills_are_loaded_with_versions() -> None:
    analysis, analysis_ref = load_skill("monitoring-analysis")
    answering, answering_ref = load_skill("answer-writing")
    assert "中国标准时间" in analysis
    assert "Markdown" in answering
    assert analysis_ref.version != answering_ref.version


def test_monitoring_registry_exposes_read_only_definition() -> None:
    registry = MonitoringToolRegistry()

    async def handler(**kwargs):
        del kwargs
        return {"items": [], "data_status": "empty"}

    registry.register("query_alerts", handler)
    definition = registry.definition("query_alerts")
    assert definition.read_only is True
    assert definition.requires_tenant_scope is True
    assert definition.fact_type == "alert"
    assert definition.presentation["title"] == "告警明细"
    assert {item["field"] for item in definition.presentation["columns"]} == {
        "alert_info",
        "status_detail",
        "time_detail",
    }


def test_build_monitoring_agent_uses_restricted_deepagents_harness() -> None:
    runtime = MonitoringRuntime(max_retries=1)
    compiled = object()
    with patch(
        "app.agents.monitoring.agent.create_deep_agent",
        return_value=compiled,
    ) as create:
        result = build_monitoring_deep_agent(runtime, model=object())

    assert result is compiled
    kwargs = create.call_args.kwargs
    assert kwargs["name"] == "monitoring_agent"
    assert kwargs["skills"] == ["/skills/"]
    assert kwargs["subagents"] == []
    assert kwargs["context_schema"].__name__ == "MonitoringHarnessContext"
    assert {tool.name for tool in kwargs["tools"]} == {
        "query_health_snapshots",
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
        "get_alert_details",
        "correlate_alerts",
        "query_metric_series",
        "query_resource_timeline",
    }
    assert {type(item) for item in kwargs["middleware"]} == {
        ModelCallLimitMiddleware,
        ModelRetryMiddleware,
        MonitoringModelCallAccountingMiddleware,
        ToolCallLimitMiddleware,
        ToolRetryMiddleware,
    }
    accounting = next(
        item
        for item in kwargs["middleware"]
        if isinstance(item, MonitoringModelCallAccountingMiddleware)
    )
    assert accounting.monitoring_runtime is runtime
    tool_limit = next(
        item for item in kwargs["middleware"] if isinstance(item, ToolCallLimitMiddleware)
    )
    model_limit = next(
        item for item in kwargs["middleware"] if isinstance(item, ModelCallLimitMiddleware)
    )
    assert tool_limit.run_limit == max(runtime.max_steps * 4, runtime.max_tool_calls + 8)
    assert model_limit.run_limit == runtime.max_model_calls
    assert isinstance(kwargs["response_format"], ToolStrategy)
    assert kwargs["permissions"][0].paths == ["/skills/**"]
    assert kwargs["permissions"][1].mode == "deny"
    assert {"write_todos", "write_file", "execute", "task"}.issubset(EXCLUDED_BUILTIN_TOOLS)


def test_tool_runtime_context_is_hidden_from_model_schema() -> None:
    expected_inputs = {
        "get_alert_details": {"fact_ids"},
        "correlate_alerts": {"fact_ids"},
        "query_metric_series": {"metric_codes", "resource_codes"},
        "query_resource_timeline": {"resource_codes", "trace_ids"},
    }
    for monitoring_tool in MONITORING_ANALYSIS_TOOLS:
        assert "runtime" not in monitoring_tool.tool_call_schema.model_fields
        assert set(monitoring_tool.tool_call_schema.model_fields) == expected_inputs.get(
            monitoring_tool.name, set()
        )


@pytest.mark.asyncio
async def test_monitoring_session_shares_context_budget_across_tools() -> None:
    session = MonitoringSession(
        question="分析平台",
        trusted_context={},
        registry=object(),
        runtime=MonitoringRuntime(max_context_items=10),
    )
    for index, name in enumerate(
        (
            "query_health_snapshots",
            "query_alerts",
            "query_metrics",
            "query_events",
            "query_tasks",
        )
    ):
        result = await session.store_fact(
            name,
            {"items": [{"id": index * 3 + offset} for offset in range(3)]},
        )
        assert result["items_truncated"] is True

    assert sum(len(item["items"]) for item in session.facts.values()) == 10
    assert all(len(item["items"]) == 2 for item in session.facts.values())


@pytest.mark.asyncio
async def test_monitoring_result_records_deep_agent_skills_and_registry_calls() -> None:
    registry = MonitoringToolRegistry()

    async def handler(**kwargs):
        assert kwargs["scope_key"] == "platform"
        return {
            "items": [{"id": "health-1", "status": "healthy", "evidence_type": "health"}],
            "data_status": "ready",
        }

    for name in (
        "query_health_snapshots",
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
    ):
        registry.register(name, handler)
    result = await MonitoringAgent(
        tools=registry,
        agent_factory=lambda runtime: FakeMonitoringDeepAgent(),
    ).analyze(
        question="最近平台运行正常吗",
        context={
            "user_id": "1",
            "role": "platform_super_admin",
            "scope_key": "platform",
        },
    )
    assert {item["name"] for item in result["skill_refs"]} == {
        "monitoring-analysis",
        "answer-writing",
    }
    assert result["model_call_count"] == 2
    assert len(result["tool_calls"]) == 5
    # 工具事实包含告警时，程序结论覆盖模型声明的 normal。
    assert result["conclusion"] == "warning"


@pytest.mark.asyncio
async def test_missing_provider_structured_output_uses_deterministic_convergence() -> None:
    registry = MonitoringToolRegistry()

    async def handler(**kwargs):
        del kwargs
        return {"items": [], "data_status": "empty"}

    registry.register("query_alerts", handler)
    result = await MonitoringAgent(
        tools=registry,
        agent_factory=lambda runtime: UnstructuredMonitoringDeepAgent(),
        structured_output_repair=_unavailable_repair,
    ).analyze(
        question="最近有哪些活动告警",
        context={
            "user_id": "1",
            "role": "platform_super_admin",
            "scope_key": "platform",
        },
    )

    assert result["status"] == "completed"
    assert result["planning"]["mode"] == "fallback"
    assert result["planning"]["error"] == "StructuredOutputMissing"
    assert result["conclusion"] == "unknown"


@pytest.mark.asyncio
async def test_missing_monitoring_terminal_is_repaired_without_requerying_tools() -> None:
    registry = MonitoringToolRegistry()
    query_count = 0

    async def handler(**kwargs):
        nonlocal query_count
        del kwargs
        query_count += 1
        return {
            "items": [{"id": "alert-1", "status": "firing", "severity": "warning"}],
            "data_status": "ready",
        }

    async def repair(**kwargs):
        assert kwargs["schema"] is MonitoringAgentOutput
        assert set(kwargs["evidence_payload"]["facts"]) == {"query_alerts"}
        return StructuredOutputRepairResult(
            value=MonitoringAgentOutput(
                intent="evidence_review",
                goal="列出活动告警",
                requested_view="告警明细",
                answer_markdown="已取得中国标准时间范围内的活动告警明细，请结合证据继续核查。",
                conclusion_ack="warning",
                evidence_refs=["alert-1"],
                layout_reason="按告警明细展示",
                confidence=0.9,
            ),
            attempted=True,
        )

    registry.register("query_alerts", handler)
    result = await MonitoringAgent(
        tools=registry,
        agent_factory=lambda runtime: UnstructuredMonitoringDeepAgent(),
        structured_output_repair=repair,
    ).analyze(
        question="最近有哪些活动告警",
        context={
            "user_id": "1",
            "role": "platform_super_admin",
            "scope_key": "platform",
        },
    )

    assert query_count == 1
    assert result["planning"]["mode"] == "llm"
    assert result["planning"]["error"] is None
    assert result["answering"]["mode"] == "llm"


@pytest.mark.asyncio
async def test_model_timeout_preserves_collected_facts_and_converges() -> None:
    registry = MonitoringToolRegistry()

    async def handler(**kwargs):
        del kwargs
        return {
            "items": [
                {
                    "id": f"alert-{index}",
                    "evidence_type": "alert",
                    "title": title,
                    "status": "firing",
                    "severity": "critical" if index == 1 else "warning",
                    "resource_type": "worker" if index == 1 else "service",
                    "current_value": 1 / 3 if index == 1 else 100 + index,
                    "occurred_at": _window()[1] - timedelta(minutes=index),
                }
                for index, title in enumerate(
                    (
                        "Worker 心跳过期",
                        "问答延迟过高",
                        "数据库连接紧张",
                        "索引任务积压",
                    ),
                    1,
                )
            ],
            "data_status": "ready",
        }

    async def health_handler(**kwargs):
        del kwargs
        return {
            "items": [
                {
                    "id": "health-1",
                    "evidence_type": "health",
                    "title": "API 健康检查",
                    "status": "healthy",
                    "occurred_at": _window()[1],
                }
            ],
            "data_status": "ready",
        }

    registry.register("query_alerts", handler)
    registry.register("query_health_snapshots", health_handler)
    result = await MonitoringAgent(
        runtime=MonitoringRuntime(timeout_seconds=0.15),
        tools=registry,
        agent_factory=lambda runtime: MultiSourceSlowFinalMonitoringDeepAgent(),
    ).analyze(
        question="4条都是什么样子的告警",
        context={
            "user_id": "1",
            "role": "platform_super_admin",
            "scope_key": "platform",
        },
    )

    assert result["status"] == "completed"
    assert result["planning"]["mode"] == "fallback"
    assert result["planning"]["error"] == "ModelTimeout"
    assert result["answering"]["mode"] == "fallback"
    assert result["conclusion"] == "abnormal"
    assert [item["id"] for item in result["evidence"][:4]] == [
        "alert-1",
        "alert-2",
        "alert-3",
        "alert-4",
    ]
    assert result["tool_calls"][0]["status"] == "completed"
    assert "### 告警明细" in result["answer"]
    assert "| 告警信息 | 状态详情 | 时间信息 |" in result["answer"]
    for title in ("Worker 心跳过期", "问答延迟过高", "数据库连接紧张", "索引任务积压"):
        assert title in result["answer"]
    assert "API 健康检查" not in result["answer"]
    assert "外部模型响应超时" not in result["answer"]
    assert "当前值：0.33" in result["answer"]
    assert "0.3333333333333333" not in result["answer"]
    assert result["fact_set"]["sources"][0]["fact_type"] == "alert"
    assert result["presentation"]["type"] == "alert_list"
    assert "共取得 4 条告警" in result["presentation"]["summary_markdown"]


@pytest.mark.asyncio
async def test_provider_error_preserves_monitoring_facts_and_converges() -> None:
    registry = MonitoringToolRegistry()

    async def handler(**kwargs):
        del kwargs
        return {
            "items": [
                {
                    "id": "alert-provider-1",
                    "evidence_type": "alert",
                    "status": "firing",
                    "severity": "warning",
                }
            ],
            "data_status": "ready",
        }

    registry.register("query_alerts", handler)
    result = await MonitoringAgent(
        tools=registry,
        agent_factory=lambda runtime: ProviderFailureMonitoringDeepAgent(),
    ).analyze(
        question="最近有哪些活动告警",
        context={
            "user_id": "1",
            "role": "platform_super_admin",
            "scope_key": "platform",
        },
    )

    assert result["status"] == "completed"
    assert result["planning"]["error"] == "ProviderError"
    assert result["answering"]["mode"] == "fallback"
    assert result["conclusion"] == "warning"
    assert [item["id"] for item in result["evidence"]] == ["alert-provider-1"]


@pytest.mark.asyncio
async def test_cross_turn_reference_uses_authorized_prior_fact_set() -> None:
    prior_fact_set = {
        "id": "monitor-facts-prior",
        "sources": [
            {
                "tool_name": "query_alerts",
                "fact_type": "alert",
                "presentation": {
                    "fact_type": "alert",
                    "title": "告警明细",
                    "columns": [
                        {"field": "title", "label": "告警名称"},
                        {"field": "severity", "label": "告警级别"},
                        {"field": "status", "label": "当前状态"},
                    ],
                },
                "items": [
                    {
                        "id": "alert-prior-1",
                        "title": "Worker 心跳过期",
                        "severity": "critical",
                        "status": "firing",
                    }
                ],
            }
        ],
    }
    result = await MonitoringAgent(
        tools=MonitoringToolRegistry(),
        agent_factory=lambda runtime: NoToolProviderFailureMonitoringDeepAgent(),
    ).analyze(
        question="这1条具体是什么？",
        context={
            "user_id": "1",
            "role": "platform_super_admin",
            "scope_key": "platform",
            "prior_fact_set": prior_fact_set,
        },
    )

    assert result["status"] == "completed"
    assert result["planning"]["error"] == "ProviderError"
    assert result["conclusion"] == "unknown"
    assert "上一轮已授权查询结果" in result["answer"]
    assert "Worker 心跳过期" in result["answer"]
    assert [item["id"] for item in result["evidence"]] == ["alert-prior-1"]
    assert result["fact_set"]["id"] == "monitor-facts-prior"
