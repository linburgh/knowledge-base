from __future__ import annotations

import re
from typing import Any

from .models import AnalysisConclusion, MonitoringAgentOutput

_CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_FORBIDDEN_OUTPUT = (
    "Asia/Shanghai",
    "query_health_snapshots",
    "query_alerts",
    "query_metrics",
    "query_events",
    "query_tasks",
    "```",
    "<script",
)


def _internal_codes(value: Any) -> set[str]:
    codes: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_code") and isinstance(item, str) and item:
                codes.add(item)
            codes.update(_internal_codes(item))
    elif isinstance(value, list):
        for item in value:
            codes.update(_internal_codes(item))
    return codes


def _evidence_ids(value: Any) -> set[str]:
    identifiers: set[str] = set()
    if isinstance(value, dict):
        identifier = value.get("id")
        if isinstance(identifier, (str, int)) and str(identifier):
            identifiers.add(str(identifier))
        for item in value.values():
            identifiers.update(_evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            identifiers.update(_evidence_ids(item))
    return identifiers


def validate_monitoring_output(
    output: MonitoringAgentOutput,
    conclusion: AnalysisConclusion,
    facts: dict[str, dict[str, Any]],
) -> None:
    """校验客户可见回答；失败时由 Agent 入口收敛为确定性回答。"""
    markdown = output.answer_markdown
    if not 20 <= len(markdown) <= 6000:
        raise ValueError("回答长度不符合要求")
    if not _CHINESE_PATTERN.search(markdown):
        raise ValueError("回答未使用中文")
    if output.conclusion_ack != conclusion:
        raise ValueError("回答确认的结论编码与程序结论不一致")
    if "中国标准时间" not in markdown:
        raise ValueError("回答未标明中国标准时间")
    if any(item.lower() in markdown.lower() for item in _FORBIDDEN_OUTPUT):
        raise ValueError("回答包含不允许展示的内部内容")
    if any(code in markdown for code in _internal_codes(facts)):
        raise ValueError("回答直接展示了内部资源编码")
    if set(output.evidence_refs) - _evidence_ids(facts):
        raise ValueError("回答引用了本轮授权事实之外的证据")


__all__ = ("validate_monitoring_output",)
