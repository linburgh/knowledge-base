from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.agents.monitoring.agent import MonitoringAgent
from app.agents.monitoring.correlation import correlate_alert_items
from app.agents.monitoring.runtime import MonitoringAgentError, MonitoringRuntime
from app.agents.monitoring.state import MonitoringSession
from app.agents.monitoring.tools import MONITORING_ANALYSIS_TOOLS
from app.agents.monitoring.tools.registry import MonitoringToolRegistry
from app.core.common.structured_output import StructuredOutputRepairResult
from app.core.services.monitoring import analysis_tools


class _UnstructuredInvestigationAgent:
    async def ainvoke(self, inputs, *, context, config):
        del inputs, config
        runtime = SimpleNamespace(context=context)
        by_name = {tool.name: tool for tool in MONITORING_ANALYSIS_TOOLS}
        await by_name["query_alerts"].coroutine(runtime=runtime)
        await by_name["correlate_alerts"].coroutine(
            fact_ids=["alert-1", "alert-2"], runtime=runtime
        )
        return {"messages": []}


class _UnstructuredCauseAgent:
    async def ainvoke(self, inputs, *, context, config):
        del inputs, config
        runtime = SimpleNamespace(context=context)
        by_name = {tool.name: tool for tool in MONITORING_ANALYSIS_TOOLS}
        alerts = await by_name["query_alerts"].coroutine(runtime=runtime)
        fact_ids = [item["id"] for item in alerts["items"]]
        await by_name["get_alert_details"].coroutine(fact_ids=fact_ids, runtime=runtime)
        await by_name["correlate_alerts"].coroutine(fact_ids=fact_ids, runtime=runtime)
        await by_name["query_metric_series"].coroutine(
            metric_codes=["qa_citation_rate", "qa_success_rate", "qa_error_rate"],
            resource_codes=[],
            runtime=runtime,
        )
        await by_name["query_resource_timeline"].coroutine(
            resource_codes=[],
            trace_ids=[],
            runtime=runtime,
        )
        return {"messages": []}


async def _unavailable_repair(**kwargs):
    del kwargs
    return StructuredOutputRepairResult(
        value=None,
        attempted=True,
        error="RepairProviderError:RateLimitError",
    )


def test_alert_correlation_groups_same_business_signature_without_claiming_duplicate() -> None:
    now = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
    items = [
        {
            "id": f"alert-{index}",
            "title": "指标异常：问答错误率",
            "metric_code": "qa_error_rate",
            "metric_name": "问答错误率",
            "resource_type": "api",
            "resource_code": "qa-api",
            "resource_name": "全平台",
            "scope_key": "platform",
            "rule_id": "7",
            "last_fired_at": now + timedelta(seconds=index * 20),
        }
        for index in range(1, 3)
    ]

    result = correlate_alert_items(items)

    assert len(result) == 1
    assert result[0]["member_count"] == 2
    assert result[0]["status"] == "likely_duplicate"
    assert result[0]["status_name"] == "高度相似"
    assert "不能单独证明数据库重复写入" in result[0]["judgment_boundary"]


@pytest.mark.asyncio
async def test_runtime_rejects_identical_successful_query_but_allows_new_arguments() -> None:
    registry = MonitoringToolRegistry()

    async def handler(**_kwargs):
        return {"items": [], "data_status": "empty"}

    registry.register("query_alerts", handler)
    runtime = MonitoringRuntime()
    session = MonitoringSession(
        question="查询告警",
        trusted_context={},
        registry=registry,
        runtime=runtime,
    )
    now = datetime.now(UTC)
    arguments = {
        "window_start": now - timedelta(hours=1),
        "window_end": now,
        "scope_key": "platform",
    }
    context = {
        "role": "platform_super_admin",
        "user_id": "1",
        "scope_key": "platform",
        "_monitoring_session": session,
    }

    await runtime.invoke_tool(
        registry=registry,
        name="query_alerts",
        arguments=arguments,
        context=context,
    )
    with pytest.raises(MonitoringAgentError, match="不允许重复执行相同查询"):
        await runtime.invoke_tool(
            registry=registry,
            name="query_alerts",
            arguments=arguments,
            context=context,
        )


@pytest.mark.asyncio
async def test_registered_investigation_tools_filter_and_correlate_authorized_alerts(
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)

    async def list_alerts(*_args, **_kwargs):
        return [
            {
                "id": index,
                "alert_key": f"rule-7:platform:{index}",
                "rule_id": 7,
                "metric_code": "qa_error_rate",
                "alert_title": "指标异常：qa_error_rate",
                "severity": "critical",
                "status": "firing",
                "resource_type": "api",
                "resource_code": "qa-api",
                "current_value": 1,
                "threshold": 0.05,
                "sample_count": 10,
                "first_fired_at": now - timedelta(minutes=5),
                "last_fired_at": now - timedelta(seconds=index * 10),
            }
            for index in (1, 2)
        ]

    async def list_definitions(*_args, **_kwargs):
        return [
            {
                "metric_code": "qa_error_rate",
                "metric_name": "问答错误率",
                "metric_domain": "qa",
                "status": "active",
                "version": 1,
            }
        ]

    monkeypatch.setattr(analysis_tools.alert_db, "list", list_alerts)
    monkeypatch.setattr(analysis_tools.definition_db, "list", list_definitions)
    registry = analysis_tools.build_monitoring_tool_registry(scope=None)
    token = analysis_tools.DB.set(object())
    try:
        details = await registry.invoke(
            "get_alert_details",
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(minutes=1),
            scope_key="platform",
            fact_ids=["alert-2"],
        )
        correlation = await registry.invoke(
            "correlate_alerts",
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(minutes=1),
            scope_key="platform",
            fact_ids=["alert-1", "alert-2"],
        )
    finally:
        analysis_tools.DB.reset(token)

    assert [item["id"] for item in details["items"]] == ["alert-2"]
    assert details["items"][0]["title"] == "指标异常：问答错误率"
    assert correlation["fact_type"] == "alert_correlation"
    assert correlation["items"][0]["member_count"] == 2
    assert correlation["items"][0]["status_name"] == "高度相似"


@pytest.mark.asyncio
async def test_model_convergence_failure_keeps_alert_details_and_correlation_answer() -> None:
    registry = MonitoringToolRegistry()
    alerts = [
        {
            "id": f"alert-{index}",
            "evidence_type": "alert",
            "title": "指标异常：问答错误率",
            "alert_info": "指标异常：问答错误率；严重 · 知识库问答；资源：全平台",
            "status_detail": "告警中；当前值：1.00；阈值：0.05；样本：10",
            "time_detail": "最近：2026年08月09日 08:00:00；首次：2026年08月09日 07:55:00",
            "status": "firing",
            "severity": "critical",
        }
        for index in (1, 2)
    ]
    correlation = correlate_alert_items(
        [
            {
                **item,
                "metric_code": "qa_error_rate",
                "metric_name": "问答错误率",
                "resource_type": "api",
                "resource_code": "qa-api",
                "resource_name": "全平台",
                "scope_key": "platform",
                "rule_id": "7",
                "last_fired_at": datetime(2026, 8, 9, 8, 0, tzinfo=UTC),
            }
            for item in alerts
        ]
    )

    async def query_alerts(**_kwargs):
        return {"items": alerts, "data_status": "ready"}

    async def correlate(**_kwargs):
        return {"items": correlation, "data_status": "ready"}

    registry.register("query_alerts", query_alerts)
    registry.register("correlate_alerts", correlate)
    result = await MonitoringAgent(
        tools=registry,
        agent_factory=lambda _runtime: _UnstructuredInvestigationAgent(),
    ).analyze(
        question="这两条告警分别是什么，是否重复？",
        context={
            "user_id": "1",
            "role": "platform_super_admin",
            "scope_key": "platform",
        },
    )

    assert result["answering"]["mode"] == "fallback"
    assert "### 告警明细" in result["answer"]
    assert "### 告警关联" in result["answer"]
    assert "不能单独证明数据库重复写入" in result["answer"]
    assert result["presentation"]["type"] == "alert_list"
    assert result["investigation"]["query_count"] == 2


@pytest.mark.asyncio
async def test_cause_question_keeps_structured_analysis_when_model_and_repair_fail() -> None:
    registry = MonitoringToolRegistry()
    occurred_at = datetime(2026, 8, 9, 7, 45, tzinfo=UTC)
    alerts = [
        {
            "id": "alert-citation-tenant",
            "evidence_type": "alert",
            "metric_name": "问答引用率",
            "resource_name": "当前租户",
            "scope_key": "tenant:1",
            "current_value": 0.33,
            "threshold": 0.8,
            "sample_count": 3,
            "status": "firing",
            "severity": "critical",
            "last_fired_at": occurred_at,
        },
        {
            "id": "alert-citation-platform",
            "evidence_type": "alert",
            "metric_name": "问答引用率",
            "resource_name": "全平台",
            "scope_key": "platform",
            "current_value": 0.33,
            "threshold": 0.8,
            "sample_count": 3,
            "status": "firing",
            "severity": "critical",
            "last_fired_at": occurred_at,
        },
        {
            "id": "alert-success-tenant",
            "evidence_type": "alert",
            "metric_name": "问答成功率",
            "resource_name": "当前租户",
            "scope_key": "tenant:1",
            "current_value": 0,
            "threshold": 0.95,
            "sample_count": 2,
            "status": "firing",
            "severity": "critical",
            "last_fired_at": occurred_at,
        },
        {
            "id": "alert-error-tenant",
            "evidence_type": "alert",
            "metric_name": "问答错误率",
            "resource_name": "当前租户",
            "scope_key": "tenant:1",
            "current_value": 1,
            "threshold": 0.05,
            "sample_count": 2,
            "status": "firing",
            "severity": "critical",
            "last_fired_at": occurred_at,
        },
    ]

    async def alert_handler(**_kwargs):
        return {"items": alerts, "data_status": "ready"}

    async def correlation_handler(**_kwargs):
        return {"items": [], "data_status": "empty"}

    async def metric_handler(**_kwargs):
        return {
            "items": [
                {
                    "id": "metric-citation",
                    "evidence_type": "metric_series",
                    "metric_name": "问答引用率",
                    "metric_value": 0.33,
                    "window_end": occurred_at,
                }
            ],
            "data_status": "ready",
        }

    async def timeline_handler(**_kwargs):
        return {"items": [], "data_status": "empty"}

    registry.register("query_alerts", alert_handler)
    registry.register("get_alert_details", alert_handler)
    registry.register("correlate_alerts", correlation_handler)
    registry.register("query_metric_series", metric_handler)
    registry.register("query_resource_timeline", timeline_handler)
    result = await MonitoringAgent(
        tools=registry,
        agent_factory=lambda _runtime: _UnstructuredCauseAgent(),
        structured_output_repair=_unavailable_repair,
    ).analyze(
        question="分析一下这四条告警产生的原因吗",
        context={
            "user_id": "1",
            "role": "platform_super_admin",
            "scope_key": "platform",
        },
    )

    assert result["answering"]["mode"] == "fallback"
    assert "### 原因结论" in result["answer"]
    assert "### 直接触发原因" in result["answer"]
    assert "问答引用率当前值为0.33，低于阈值0.80" in result["answer"]
    assert "问答成功率当前值为0.00，低于阈值0.95" in result["answer"]
    assert "问答错误率当前值为1.00，高于阈值0.05" in result["answer"]
    assert any(
        item["relation_type"] == "same_sample_window"
        for item in result["investigation"]["relations"]
    ), result["investigation"]["relations"]
    assert "尚无充分证据定位到底层组件根因" in result["answer"]
    assert result["presentation"]["type"] == "composite"
    assert [block["type"] for block in result["presentation"]["blocks"]][-1] == "alert_list"
    assert result["investigation"]["analysis_goal"]
    assert len(result["investigation"]["causal_assessment"]["direct_causes"]) == 3
