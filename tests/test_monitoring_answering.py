from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.monitoring.answering import (
    DeterministicMarkdownAnswerComposer,
    GroundedMarkdownAnswerComposer,
    ResilientMonitoringAnswerComposer,
)
from app.agents.monitoring.models import AnalysisConclusion
from app.agents.monitoring.planning import build_plan


class _AnswerModel:
    def __init__(self, *outputs: dict | Exception) -> None:
        self.outputs = list(outputs)
        self.call_count = 0

    def with_structured_output(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, _messages):
        output = self.outputs[min(self.call_count, len(self.outputs) - 1)]
        self.call_count += 1
        if isinstance(output, Exception):
            raise output
        return output


def _plan():
    return build_plan(
        "昨天平台运行正常吗",
        default_time_range="1h",
        now=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_grounded_composer_generates_dynamic_chinese_markdown():
    markdown = """> **平台整体运行正常。**

### 关键证据

| 检查维度 | 检查结果 |
| --- | --- |
| 健康状态 | 服务状态正常 |
| 告警情况 | 未发现异常告警 |

时间范围为昨天，采用中国标准时间。

### 持续观察

1. 继续关注核心指标趋势。
2. 如出现新告警，再结合事件链路核查。"""
    composer = GroundedMarkdownAnswerComposer(
        _AnswerModel(
            {
                "answer_markdown": markdown.replace(
                    "平台整体运行正常", "已覆盖的监控数据未显示平台异常"
                ),
                "conclusion_ack": "normal",
                "evidence_refs": ["health-1"],
                "fact_refs": ["健康状态正常"],
                "layout_reason": "存在多个检查维度，使用表格归纳",
            }
        )
    )

    result = await composer.compose(
        question="昨天平台运行正常吗",
        plan=_plan(),
        conclusion=AnalysisConclusion.NORMAL,
        facts={"query_health_snapshots": {"items": [{"id": "health-1", "status": "healthy"}]}},
        limitations=[],
        fallback_markdown="降级回答",
    )

    assert result.mode == "llm"
    assert result.markdown.startswith("> **已覆盖的监控数据未显示平台异常。**")
    assert "| 检查维度 | 检查结果 |" in result.markdown
    assert "中国标准时间" in result.markdown
    assert result.evidence_refs == ("health-1",)
    assert result.layout_reason == "存在多个检查维度，使用表格归纳"


@pytest.mark.asyncio
async def test_answer_composer_falls_back_when_model_changes_conclusion():
    composer = ResilientMonitoringAnswerComposer(
        GroundedMarkdownAnswerComposer(
            _AnswerModel(
                {
                    "answer_markdown": "> 平台存在严重异常。时间范围采用中国标准时间。",
                    "conclusion_ack": "abnormal",
                    "evidence_refs": [],
                    "fact_refs": [],
                    "layout_reason": "使用简短结论",
                }
            )
        ),
        DeterministicMarkdownAnswerComposer(),
    )

    result = await composer.compose(
        question="昨天平台运行正常吗",
        plan=_plan(),
        conclusion=AnalysisConclusion.NORMAL,
        facts={"query_health_snapshots": {"items": [{"status": "healthy"}]}},
        limitations=[],
        fallback_markdown="### 分析结论\n\n**平台整体运行正常**",
    )

    assert result.mode == "fallback"
    assert result.error == "ValueError"
    assert result.markdown == "### 分析结论\n\n**平台整体运行正常**"


@pytest.mark.asyncio
async def test_answer_composer_falls_back_when_model_exposes_resource_code():
    composer = ResilientMonitoringAnswerComposer(
        GroundedMarkdownAnswerComposer(
            _AnswerModel(
                {
                    "answer_markdown": (
                        "> **平台整体运行正常。**\n\n"
                        "时间范围采用中国标准时间，资源 indexing-worker 状态正常。"
                    ),
                    "conclusion_ack": "normal",
                    "evidence_refs": [],
                    "fact_refs": [],
                    "layout_reason": "使用简短结论",
                }
            )
        )
    )

    result = await composer.compose(
        question="昨天平台运行正常吗",
        plan=_plan(),
        conclusion=AnalysisConclusion.NORMAL,
        facts={
            "query_health_snapshots": {
                "items": [{"resource_code": "indexing-worker", "status": "healthy"}]
            }
        },
        limitations=[],
        fallback_markdown="### 分析结论\n\n**平台整体运行正常**",
    )

    assert result.mode == "fallback"
    assert result.error == "ValueError"
    assert "indexing-worker" not in result.markdown


@pytest.mark.asyncio
async def test_answer_composer_repairs_first_invalid_output():
    model = _AnswerModel(
        {
            "answer_markdown": "> 当前运行平稳。",
            "conclusion_ack": "normal",
            "evidence_refs": ["unknown-evidence"],
            "fact_refs": [],
            "layout_reason": "简短回答",
        },
        {
            "answer_markdown": (
                "> **已覆盖的监控数据未显示异常。**\n\n"
                "昨天的分析采用中国标准时间。\n\n"
                "- 健康状态记录显示服务运行正常。\n"
                "- 当前没有发现需要立即处置的监控异常。\n"
                "- 建议继续关注核心指标趋势。"
            ),
            "conclusion_ack": "normal",
            "evidence_refs": ["health-1"],
            "fact_refs": ["健康状态正常"],
            "layout_reason": "证据较少，使用引用块和列表",
        },
    )
    composer = GroundedMarkdownAnswerComposer(model)

    result = await composer.compose(
        question="昨天平台运行正常吗",
        plan=_plan(),
        conclusion=AnalysisConclusion.NORMAL,
        facts={"query_health_snapshots": {"items": [{"id": "health-1", "status": "healthy"}]}},
        limitations=[],
        fallback_markdown="降级回答",
    )

    assert model.call_count == 2
    assert result.mode == "llm"
    assert result.evidence_refs == ("health-1",)
