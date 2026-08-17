"""自主评测报告对象构建及 Markdown、JSON 渲染。"""

from __future__ import annotations

import json
from typing import Any

from .config import config_snapshot
from .models import (
    CaseResult,
    EvaluationAgentOutput,
    EvaluationConfig,
    EvaluationMetrics,
)


def build_report(
    config: EvaluationConfig,
    results: list[CaseResult],
    metrics: EvaluationMetrics,
    *,
    analysis: EvaluationAgentOutput | None = None,
) -> dict[str, Any]:
    """汇总配置快照、逐题结果、指标和 Agent 审计元数据。"""
    failures = [item for item in results if item.status != "completed"]
    citation_anomalies = [
        item for item in results if item.status == "completed" and item.citation_count == 0
    ]
    findings: list[str] = []
    if failures:
        findings.append(f"发现 {len(failures)} 道题未正常完成，请查看失败样品和终止原因。")
    if citation_anomalies:
        findings.append(f"发现 {len(citation_anomalies)} 道已完成题目没有引用资料。")
    if not findings:
        findings.append("本次评测未发现错误、超时、降级或引用缺失样品。")
    return {
        "task": {"kb_id": config.kb_id, "question_source": config.questions_source},
        "dataset": {
            "total": len(results),
            "sources": sorted({item.question_source for item in results}),
        },
        "config_snapshot": config_snapshot(config),
        "metrics": metrics.model_dump(mode="json"),
        "failures": [item.model_dump(mode="json") for item in failures],
        "citation_anomalies": [item.model_dump(mode="json") for item in citation_anomalies],
        "summary": (
            "本次评测整体通过。" if metrics.conclusion == "passed" else "本次评测未通过全部门禁。"
        ),
        "findings": findings,
        "agent_analysis": {
            **(analysis.model_dump(mode="json") if analysis else {}),
        },
        "conclusion": metrics.conclusion,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """将结构化报告渲染为便于人工评审的中文 Markdown。"""
    metrics = report["metrics"]["metrics"]
    lines = [
        "# 自主评测报告",
        "",
        f"- 知识库：{report['task']['kb_id']}",
        f"- 问题数：{report['dataset']['total']}",
        f"- 结论：{report['conclusion']}",
        "",
        "## 指标",
        "",
        "| 指标 | 实际值 | 样本数 |",
        "| --- | ---: | ---: |",
    ]
    lines.extend(
        f"| {name} | {value.get('value', '无法评估')} | {value.get('sample_count', 0)} |"
        for name, value in metrics.items()
    )
    return "\n".join(lines) + "\n"


def render_json(report: dict[str, Any]) -> str:
    """将结构化报告渲染为保留中文字符的缩进 JSON。"""
    return json.dumps(report, ensure_ascii=False, indent=2)
