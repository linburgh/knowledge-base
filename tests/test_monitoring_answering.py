from __future__ import annotations

import pytest

from app.agents.monitoring.models import (
    AnalysisConclusion,
    MonitoringAgentOutput,
)
from app.agents.monitoring.validation import validate_monitoring_output


def _output(**overrides) -> MonitoringAgentOutput:
    values = {
        "intent": "platform_health",
        "goal": "判断平台运行状态",
        "answer_markdown": (
            "> **已覆盖的监控数据未显示异常。**\n\n"
            "分析时间采用中国标准时间，健康状态记录显示服务运行正常。"
        ),
        "conclusion_ack": "normal",
        "evidence_refs": ["health-1"],
        "fact_refs": ["健康状态正常"],
        "layout_reason": "证据较少，使用简短结论",
    }
    values.update(overrides)
    return MonitoringAgentOutput.model_validate(values)


def _facts():
    return {
        "query_health_snapshots": {
            "items": [
                {
                    "id": "health-1",
                    "status": "healthy",
                    "resource_code": "indexing-worker",
                }
            ]
        }
    }


def test_monitoring_output_accepts_grounded_chinese_markdown() -> None:
    validate_monitoring_output(_output(), AnalysisConclusion.NORMAL, _facts())


def test_monitoring_output_rejects_changed_conclusion() -> None:
    with pytest.raises(ValueError, match="结论编码"):
        validate_monitoring_output(
            _output(conclusion_ack="abnormal"),
            AnalysisConclusion.NORMAL,
            _facts(),
        )


def test_monitoring_output_rejects_unknown_evidence() -> None:
    with pytest.raises(ValueError, match="授权事实之外"):
        validate_monitoring_output(
            _output(evidence_refs=["unknown-evidence"]),
            AnalysisConclusion.NORMAL,
            _facts(),
        )


def test_monitoring_output_rejects_internal_resource_code() -> None:
    with pytest.raises(ValueError, match="内部资源编码"):
        validate_monitoring_output(
            _output(
                answer_markdown=(
                    "分析时间采用中国标准时间，资源 indexing-worker 的健康状态记录显示正常。"
                )
            ),
            AnalysisConclusion.NORMAL,
            _facts(),
        )


def test_monitoring_output_rejects_internal_tool_name() -> None:
    with pytest.raises(ValueError, match="内部内容"):
        validate_monitoring_output(
            _output(
                answer_markdown=("分析时间采用中国标准时间，已通过 query_metrics 取得监控事实。")
            ),
            AnalysisConclusion.NORMAL,
            _facts(),
        )
