from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from app.agents.monitoring import MonitoringAgent
from app.agents.monitoring.models import MonitoringAgentOutput
from app.agents.monitoring.planning import build_plan, resolve_time_range
from app.agents.monitoring.runtime import MonitoringRuntime
from app.agents.monitoring.tools import MONITORING_ANALYSIS_TOOLS
from app.agents.monitoring.tools.registry import MonitoringToolRegistry
from app.core.common.exception import BusiException
from app.core.services.monitoring import analysis_tools as monitoring_analysis_tools

_TOOLS_BY_NAME = {tool.name: tool for tool in MONITORING_ANALYSIS_TOOLS}
_DISCOVERY_TOOL_NAMES = (
    "query_health_snapshots",
    "query_alerts",
    "query_metrics",
    "query_events",
    "query_tasks",
)


class _FakeMonitoringDeepAgent:
    def __init__(
        self,
        *,
        tool_names: tuple[str, ...],
        intent: str = "platform_health",
        goal: str = "分析授权范围内的监控事实",
        label: str = "昨天",
    ) -> None:
        self.tool_names = tool_names
        self.intent = intent
        self.goal = goal
        self.label = label
        self.last_prompt = ""

    async def ainvoke(self, inputs, *, context, config):
        del config
        self.last_prompt = inputs["messages"][0]["content"]
        runtime = SimpleNamespace(context=context)
        for name in self.tool_names:
            await _TOOLS_BY_NAME[name].coroutine(runtime=runtime)
        return {
            "structured_response": MonitoringAgentOutput(
                intent=self.intent,
                goal=self.goal,
                answer_markdown="短",
                conclusion_ack="unknown",
                time_expression=self.label,
                entities=["平台服务"],
                dimensions=["健康状态", "影响范围"],
                layout_reason="将根据程序结论使用确定性降级回答",
                confidence=0.9,
            ),
            "messages": [AIMessage(content="完成分析")],
        }


def test_yesterday_is_resolved_as_shanghai_natural_day():
    resolved = resolve_time_range(
        "昨天平台运行正常吗",
        default_time_range="1h",
        now=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )

    assert resolved.label == "昨天"
    assert resolved.source == "question"
    assert resolved.start.isoformat() == "2026-07-31T00:00:00+08:00"
    assert resolved.end.isoformat() == "2026-08-01T00:00:00+08:00"


def test_explicit_time_takes_priority_over_conversation_default():
    plan = build_plan(
        "请分析2026年07月30日平台运行情况",
        default_time_range="1h",
        now=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )

    assert plan.intent.value == "platform_health"
    assert plan.time_range.label == "2026年07月30日"
    assert plan.time_range.source == "question"
    assert len(plan.tools) == 5


def test_invalid_explicit_date_falls_back_to_conversation_range():
    plan = build_plan(
        "请分析2026年02月30日平台运行情况",
        default_time_range="6h",
        now=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )

    assert plan.time_range.label == "最近6小时"
    assert plan.time_range.source == "conversation"
    assert plan.time_range.limitation == "问题中的日期无效，已使用会话默认时间范围"


@pytest.mark.asyncio
async def test_today_uses_server_authorized_shanghai_day_across_utc_date_boundary():
    fixed_now = datetime(2026, 8, 8, 23, 30, tzinfo=UTC)
    observed_arguments = {}
    registry = MonitoringToolRegistry()

    async def query_alerts(**arguments):
        observed_arguments.update(arguments)
        return {"items": [], "data_status": "empty"}

    registry.register("query_alerts", query_alerts)
    deep_agent = _FakeMonitoringDeepAgent(tool_names=("query_alerts",))
    prior_fact_set = {
        "id": "old-august-8-facts",
        "sources": [{"items": [{"id": "old-alert"}]}],
    }

    with patch("app.agents.monitoring.agent.utils.utc_now", return_value=fixed_now):
        result = await MonitoringAgent(
            tools=registry,
            agent_factory=lambda runtime: deep_agent,
        ).analyze(
            question="今天系统有异常的情况吗",
            context={
                "user_id": "1",
                "role": "platform_super_admin",
                "scope_key": "platform",
                "prior_fact_set": prior_fact_set,
            },
        )

    assert result["time_range"]["label"] == "今天"
    assert result["time_range"]["start"] == "2026-08-09T00:00:00+08:00"
    assert result["time_range"]["end"] == "2026-08-09T07:30:00+08:00"
    assert observed_arguments["window_start"].isoformat() == "2026-08-09T00:00:00+08:00"
    assert observed_arguments["window_end"].isoformat() == "2026-08-09T07:30:00+08:00"
    assert "当前时间（中国标准时间）：2026-08-09T07:30:00+08:00" in deep_agent.last_prompt
    assert "old-august-8-facts" not in deep_agent.last_prompt
    assert "上一轮事实：无" in deep_agent.last_prompt


@pytest.mark.asyncio
async def test_agent_executes_llm_semantic_plan_and_exposes_planning_metadata():
    agent = MonitoringAgent(
        tools=_registry(
            {
                "query_health_snapshots": [
                    {"id": "health-api", "status": "healthy", "evidence_type": "health"}
                ],
                "query_metrics": [
                    {
                        "id": "metric-latency",
                        "assessment_status": "normal",
                        "evidence_type": "metric",
                    }
                ],
            }
        ),
        agent_factory=lambda runtime: _FakeMonitoringDeepAgent(
            tool_names=("query_health_snapshots", "query_metrics"),
            goal="判断昨晚平台是否发生短暂性能波动",
            label="昨晚",
        ),
    )

    result = await agent.analyze(
        question="昨晚平台是不是抖了一下",
        context={"role": "platform_super_admin", "scope_key": "platform", "time_range": "1h"},
    )

    assert result["planning"]["mode"] == "llm"
    assert result["planning"]["goal"] == "判断昨晚平台是否发生短暂性能波动"
    assert result["time_range"]["label"] == "昨晚"
    assert [item["name"] for item in result["tool_calls"]] == [
        "query_health_snapshots",
        "query_metrics",
    ]
    assert "平台整体运行正常" in result["answer"]
    assert result["answer"].startswith("> **平台整体运行正常。**")
    assert "### 运行概览" in result["answer"]
    assert "| 检查维度 | 数据量 | 当前判断 |" in result["answer"]
    assert "### 后续关注" in result["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "question"),
    [
        ("general_analysis", "帮我综合看看这段时间有什么值得关注的"),
        ("impact_scope", "这次异常影响了哪些资源"),
    ],
)
async def test_customer_answer_does_not_expose_unnecessary_english(
    intent: str,
    question: str,
):
    result = await MonitoringAgent(
        tools=_registry(
            {
                "query_alerts": [
                    {
                        "id": "alert-1",
                        "status": "firing",
                        "severity": "warning",
                        "resource_code": "indexing-worker",
                        "evidence_type": "alert",
                    }
                ]
            }
        ),
        agent_factory=lambda runtime: _FakeMonitoringDeepAgent(
            tool_names=("query_alerts",),
            intent=intent,
            goal="分析当前监控事实和影响范围",
            label="最近一小时",
        ),
    ).analyze(
        question=question,
        context={"role": "platform_super_admin", "scope_key": "platform"},
    )

    assert result["agent"] == "自主监控智能体"
    for forbidden in ("Agent", "Trace", "Asia/Shanghai", "indexing-worker", "warning"):
        assert forbidden not in result["answer"]


def _registry(results: dict[str, list[dict]]) -> MonitoringToolRegistry:
    registry = MonitoringToolRegistry()

    for name in (
        "query_health_snapshots",
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
    ):

        async def handler(*, _name=name, **_kwargs):
            items = results.get(_name, [])
            return {"items": items, "data_status": "ready" if items else "empty"}

        registry.register(name, handler)
    return registry


@pytest.mark.asyncio
async def test_platform_health_uses_all_read_only_tools_and_returns_normal():
    agent = MonitoringAgent(
        tools=_registry(
            {
                "query_health_snapshots": [
                    {"id": "health-api", "status": "healthy", "evidence_type": "health"}
                ],
                "query_metrics": [
                    {
                        "id": "metric-error-rate",
                        "assessment_status": "normal",
                        "data_status": "ready",
                        "evidence_type": "metric",
                    }
                ],
            }
        ),
        agent_factory=lambda runtime: _FakeMonitoringDeepAgent(
            tool_names=_DISCOVERY_TOOL_NAMES,
        ),
    )

    result = await agent.analyze(
        question="昨天平台运行正常吗",
        context={"role": "platform_super_admin", "scope_key": "platform", "time_range": "1h"},
    )

    assert result["intent"] == "platform_health"
    assert result["conclusion"] == "normal"
    assert result["data_status"] == "complete"
    assert result["time_range"]["label"] == "昨天"
    assert result["time_range"]["source"] == "question"
    assert len(result["tool_calls"]) == 5
    assert "平台整体运行正常" in result["answer"]


@pytest.mark.asyncio
async def test_platform_health_does_not_treat_empty_alerts_as_normal():
    result = await MonitoringAgent(
        tools=_registry({}),
        agent_factory=lambda runtime: _FakeMonitoringDeepAgent(
            tool_names=_DISCOVERY_TOOL_NAMES,
        ),
    ).analyze(
        question="昨天平台运行正常吗",
        context={"role": "platform_super_admin", "scope_key": "platform", "time_range": "1h"},
    )

    assert result["conclusion"] == "unknown"
    assert result["data_status"] == "empty"
    assert "无法判断平台是否正常" in result["answer"]
    assert "未发现关联告警" not in result["answer"]


@pytest.mark.asyncio
async def test_resolved_alert_makes_period_health_warning():
    result = await MonitoringAgent(
        tools=_registry(
            {
                "query_health_snapshots": [
                    {"id": "health-api", "status": "healthy", "evidence_type": "health"}
                ],
                "query_alerts": [
                    {
                        "id": "alert-1",
                        "status": "resolved",
                        "severity": "warning",
                        "evidence_type": "alert",
                    }
                ],
                "query_metrics": [
                    {
                        "id": "metric-1",
                        "assessment_status": "normal",
                        "evidence_type": "metric",
                    }
                ],
            }
        ),
        agent_factory=lambda runtime: _FakeMonitoringDeepAgent(
            tool_names=_DISCOVERY_TOOL_NAMES,
        ),
    ).analyze(
        question="昨天平台运行正常吗",
        context={"role": "platform_super_admin", "scope_key": "platform", "time_range": "1h"},
    )

    assert result["conclusion"] == "warning"
    assert "已恢复或关闭 1 条" in result["answer"]


@pytest.mark.asyncio
async def test_registered_alert_tool_includes_resolved_alerts_in_window(monkeypatch):
    start = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)

    async def list_alerts(*_args, **_kwargs):
        return [
            {
                "id": 7,
                "metric_code": "qa_error_rate",
                "alert_title": "指标异常：qa_error_rate",
                "severity": "warning",
                "status": "resolved",
                "first_fired_at": datetime(2026, 7, 31, 2, 0, tzinfo=UTC),
                "last_fired_at": datetime(2026, 7, 31, 2, 5, tzinfo=UTC),
                "resolved_at": datetime(2026, 7, 31, 2, 10, tzinfo=UTC),
                "current_value": 180,
                "resource_type": "worker",
                "resource_code": "indexing-worker",
            }
        ]

    async def list_definitions(*_args, **_kwargs):
        return [
            {
                "metric_code": "qa_error_rate",
                "metric_name": "问答错误率",
                "status": "active",
                "version": 1,
            }
        ]

    monkeypatch.setattr(monitoring_analysis_tools.alert_db, "list", list_alerts)
    monkeypatch.setattr(monitoring_analysis_tools.definition_db, "list", list_definitions)
    registry = monitoring_analysis_tools.build_monitoring_tool_registry(scope=None)
    token = monitoring_analysis_tools.DB.set(object())
    try:
        result = await registry.invoke(
            "query_alerts",
            window_start=start,
            window_end=end,
            scope_key="platform",
        )
    finally:
        monitoring_analysis_tools.DB.reset(token)

    assert result["data_status"] == "ready"
    assert result["items"][0]["status"] == "resolved"
    assert result["items"][0]["id"] == "alert-7"
    assert result["items"][0]["title"] == "指标异常：问答错误率"
    assert "qa_error_rate" not in result["items"][0]["title"]


@pytest.mark.asyncio
async def test_alert_tool_never_falls_back_to_internal_metric_code(monkeypatch):
    now = datetime(2026, 8, 9, 7, 0, tzinfo=UTC)

    async def list_alerts(*_args, **_kwargs):
        return [
            {
                "id": 8,
                "metric_code": "unregistered_metric_code",
                "alert_title": "指标异常：unregistered_metric_code",
                "severity": "critical",
                "status": "firing",
                "first_fired_at": now,
                "last_fired_at": now,
            }
        ]

    async def list_definitions(*_args, **_kwargs):
        return []

    monkeypatch.setattr(monitoring_analysis_tools.alert_db, "list", list_alerts)
    monkeypatch.setattr(monitoring_analysis_tools.definition_db, "list", list_definitions)
    registry = monitoring_analysis_tools.build_monitoring_tool_registry(scope=None)
    token = monitoring_analysis_tools.DB.set(object())
    try:
        result = await registry.invoke(
            "query_alerts",
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(minutes=1),
            scope_key="platform",
        )
    finally:
        monitoring_analysis_tools.DB.reset(token)

    assert result["items"][0]["title"] == "指标异常：未配置中文名称"
    assert "unregistered_metric_code" not in result["items"][0]["title"]


@pytest.mark.asyncio
async def test_monitoring_tool_cannot_override_trusted_tenant_context():
    registry = _registry({})

    with pytest.raises(BusiException, match="不允许覆盖可信上下文字段"):
        await MonitoringRuntime().invoke_tool(
            registry=registry,
            name="query_alerts",
            arguments={"tenant_id": 999},
            context={"role": "tenant_admin", "tenant_id": 7},
        )
