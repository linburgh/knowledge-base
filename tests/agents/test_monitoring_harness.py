from __future__ import annotations

import pytest

from app.agents.monitoring.agent import MonitoringAgent
from app.agents.monitoring.planner import RuleBasedMonitoringPlanner
from app.agents.monitoring.skills import load_skill
from app.agents.monitoring.tools.registry import MonitoringToolRegistry


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


@pytest.mark.asyncio
async def test_monitoring_result_records_both_loaded_skills() -> None:
    registry = MonitoringToolRegistry()

    async def handler(**kwargs):
        del kwargs
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
        planner=RuleBasedMonitoringPlanner(),
    ).analyze(
        question="昨天平台运行正常吗",
        context={"role": "platform_super_admin", "scope_key": "platform"},
    )
    assert {item["name"] for item in result["skill_refs"]} == {
        "monitoring-analysis",
        "answer-writing",
    }
    assert result["model_call_count"] == 2
