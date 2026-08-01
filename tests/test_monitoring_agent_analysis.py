from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.monitoring import MonitoringAgent
from app.agents.monitoring.models import StructuredAnalysisPlan
from app.agents.monitoring.planner import (
    ResilientMonitoringPlanner,
    RuleBasedMonitoringPlanner,
    StructuredOutputMonitoringPlanner,
)
from app.agents.monitoring.planning import build_plan, resolve_time_range
from app.agents.monitoring.runtime import MonitoringRuntime
from app.agents.monitoring.tools.registry import MonitoringToolRegistry
from app.core.common.exception import BusiException
from app.core.services.monitoring import analysis_tools as monitoring_analysis_tools


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


class _StructuredModel:
    def __init__(self, output):
        self.output = output

    def with_structured_output(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, _messages):
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


@pytest.mark.asyncio
async def test_llm_structured_planner_understands_non_keyword_health_expression():
    planner = StructuredOutputMonitoringPlanner(
        _StructuredModel(
            StructuredAnalysisPlan.model_validate(
                {
                    "intent": "platform_health",
                    "goal": "判断昨晚平台是否发生短暂性能波动",
                    "time": {
                        "expression": "昨晚",
                        "label": "昨晚",
                        "start": "2026-07-31T18:00:00+08:00",
                        "end": "2026-08-01T06:00:00+08:00",
                    },
                    "entities": ["platform"],
                    "dimensions": ["availability", "latency", "error_rate"],
                    "required_tools": [
                        "query_health_snapshots",
                        "query_metrics",
                        "query_alerts",
                        "query_events",
                    ],
                    "uncertainties": [],
                    "confidence": 0.91,
                }
            )
        )
    )

    plan = await planner.plan(
        "昨晚平台是不是抖了一下",
        default_time_range="1h",
        now=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )

    assert plan.planning_mode == "llm"
    assert plan.intent.value == "platform_health"
    assert plan.goal == "判断昨晚平台是否发生短暂性能波动"
    assert plan.time_range.label == "昨晚"
    assert plan.dimensions == ("availability", "latency", "error_rate")
    assert "query_metrics" in plan.tools


@pytest.mark.asyncio
async def test_llm_plan_normalizes_open_intent_and_removes_write_tool():
    planner = StructuredOutputMonitoringPlanner(
        _StructuredModel(
            {
                "intent": "release_stability_review",
                "goal": "判断发布后服务是否稳定",
                "time": {"expression": None, "label": None, "start": None, "end": None},
                "entities": ["service"],
                "dimensions": ["release", "latency"],
                "required_tools": ["restart_worker", "query_events", "query_metrics"],
                "uncertainties": ["未提供具体发布时间"],
                "confidence": 0.72,
            }
        )
    )

    plan = await planner.plan(
        "发布之后服务稳不稳",
        default_time_range="6h",
        now=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )

    assert plan.intent.value == "general_analysis"
    assert plan.tools == ("query_events", "query_metrics")
    assert "检测到未授权工具，已从查询计划中移除" in plan.uncertainties
    assert "检测到未登记的分析意图，已按通用分析处理" in plan.uncertainties


@pytest.mark.asyncio
async def test_llm_planner_failure_uses_limited_rule_fallback():
    planner = ResilientMonitoringPlanner(
        StructuredOutputMonitoringPlanner(_StructuredModel(RuntimeError("planner unavailable")))
    )

    plan = await planner.plan(
        "昨晚平台是不是抖了一下",
        default_time_range="1h",
        now=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )

    assert plan.planning_mode == "fallback"
    assert plan.planning_error == "RuntimeError"
    assert any("有限规则降级规划" in item for item in plan.uncertainties)


@pytest.mark.asyncio
async def test_agent_executes_llm_semantic_plan_and_exposes_planning_metadata():
    planner = StructuredOutputMonitoringPlanner(
        _StructuredModel(
            {
                "intent": "platform_health",
                "goal": "判断昨晚平台是否发生短暂性能波动",
                "time": {
                    "expression": "昨晚",
                    "label": "昨晚",
                    "start": "2026-07-31T18:00:00+08:00",
                    "end": "2026-08-01T06:00:00+08:00",
                },
                "entities": ["platform"],
                "dimensions": ["latency", "error_rate"],
                "required_tools": ["query_health_snapshots", "query_metrics"],
                "uncertainties": [],
                "confidence": 0.9,
            }
        )
    )
    agent = MonitoringAgent(
        planner=planner,
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
    planner = StructuredOutputMonitoringPlanner(
        _StructuredModel(
            {
                "intent": intent,
                "goal": "分析当前监控事实和影响范围",
                "time": {
                    "expression": "最近一小时",
                    "label": "最近一小时",
                    "start": "2026-08-01T09:00:00+08:00",
                    "end": "2026-08-01T10:00:00+08:00",
                },
                "entities": ["平台服务"],
                "dimensions": ["健康状态", "影响范围"],
                "required_tools": ["query_alerts"],
                "uncertainties": [],
                "confidence": 0.9,
            }
        )
    )
    result = await MonitoringAgent(
        planner=planner,
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
        planner=RuleBasedMonitoringPlanner(),
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
        planner=RuleBasedMonitoringPlanner(),
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
        planner=RuleBasedMonitoringPlanner(),
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
                "alert_title": "Worker 心跳过期",
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

    monkeypatch.setattr(monitoring_analysis_tools.alert_db, "list", list_alerts)
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
