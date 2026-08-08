from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .models import AnalysisConclusion, AnalysisPlan

MONITORING_TIMEZONE = ZoneInfo("Asia/Shanghai")

_STATUS_NAMES = {
    "healthy": "正常",
    "normal": "正常",
    "ok": "正常",
    "warning": "预警",
    "degraded": "降级",
    "stale": "数据过期",
    "failed": "失败",
    "failure": "失败",
    "error": "异常",
    "abnormal": "异常",
    "firing": "告警中",
    "acknowledged": "已确认",
    "resolved": "已恢复",
    "closed": "已关闭",
    "completed": "已完成",
    "running": "运行中",
    "unknown": "未知",
}
_SEVERITY_NAMES = {
    "critical": "严重",
    "warning": "警告",
    "info": "提示",
    "unknown": "未知",
}
_RESOURCE_TYPE_NAMES = {
    "api": "接口服务",
    "service": "服务",
    "worker": "Worker",
    "database": "数据库",
    "dependency": "外部依赖",
    "knowledge_base": "知识库",
    "index": "索引",
}

# 展示协议属于工具能力声明，不属于用户问法分类。增加新的事实工具时，只需声明
# 安全字段和中文标签，通用渲染器即可在模型终态不可用时展示真实事实。
TOOL_PRESENTATIONS: dict[str, dict[str, Any]] = {
    "query_alerts": {
        "fact_type": "alert",
        "title": "告警明细",
        "view_terms": ["告警", "预警", "报警"],
        "columns": [
            {"field": "title", "label": "告警名称"},
            {"field": "severity", "label": "告警级别"},
            {"field": "status", "label": "当前状态"},
            {"field": "resource_type", "label": "资源类型"},
            {"field": "current_value", "label": "当前值"},
            {"field": "occurred_at", "label": "最近触发时间"},
        ],
    },
    "query_health_snapshots": {
        "fact_type": "health",
        "title": "健康状态明细",
        "view_terms": ["健康状态", "健康检查", "服务状态"],
        "columns": [
            {"field": "title", "label": "检查对象"},
            {"field": "status", "label": "当前状态"},
            {"field": "summary", "label": "检查结果"},
            {"field": "occurred_at", "label": "检查时间"},
        ],
    },
    "query_metrics": {
        "fact_type": "metric",
        "title": "指标明细",
        "view_terms": ["指标", "度量", "数值"],
        "columns": [
            {"field": "title", "label": "指标名称"},
            {"field": "summary", "label": "指标结果"},
            {"field": "assessment_status", "label": "评估状态"},
            {"field": "occurred_at", "label": "统计时间"},
        ],
    },
    "query_events": {
        "fact_type": "event",
        "title": "事件明细",
        "view_terms": ["事件", "异常记录", "变更记录"],
        "columns": [
            {"field": "title", "label": "事件类型"},
            {"field": "status", "label": "事件状态"},
            {"field": "summary", "label": "事件摘要"},
            {"field": "occurred_at", "label": "发生时间"},
        ],
    },
    "query_tasks": {
        "fact_type": "task",
        "title": "任务明细",
        "view_terms": ["任务", "作业", "执行记录"],
        "columns": [
            {"field": "title", "label": "任务事件"},
            {"field": "status", "label": "任务状态"},
            {"field": "summary", "label": "任务摘要"},
            {"field": "occurred_at", "label": "发生时间"},
        ],
    },
}

_REFERENCE_PATTERN = re.compile(
    r"(这些|那些|它们|它俩|上述|刚才|前面|其中|分别|第[一二三四五六七八九十\d]+"
    r"|这\s*\d+\s*(?:条|个)|那\s*\d+\s*(?:条|个))"
)


def presentation_for_tool(name: str) -> dict[str, Any]:
    return dict(TOOL_PRESENTATIONS.get(name) or {})


def references_prior_facts(question: str) -> bool:
    """只识别跨轮指代，不承担业务意图分类。"""
    return bool(_REFERENCE_PATTERN.search(question))


def _display_value(field: str, value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, datetime):
        current = value
        if current.tzinfo is None:
            current = current.replace(tzinfo=MONITORING_TIMEZONE)
        return current.astimezone(MONITORING_TIMEZONE).strftime("%Y年%m月%d日 %H:%M:%S")
    text = str(value)
    if field in {"status", "assessment_status"}:
        text = _STATUS_NAMES.get(text.lower(), text)
    elif field == "severity":
        text = _SEVERITY_NAMES.get(text.lower(), text)
    elif field == "resource_type":
        text = _RESOURCE_TYPE_NAMES.get(text.lower(), text)
    return text.replace("|", "｜").replace("\n", " ").strip()[:500] or "—"


def _time_description(plan: AnalysisPlan) -> str:
    start = plan.time_range.start.strftime("%Y年%m月%d日 %H:%M:%S")
    end = plan.time_range.end.strftime("%Y年%m月%d日 %H:%M:%S")
    return f"{start}—{end}，中国标准时间"


def _sources_from_facts(facts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    sources = []
    for tool_name, payload in facts.items():
        items = list(payload.get("items") or [])
        if not items:
            continue
        presentation = payload.get("presentation") or presentation_for_tool(tool_name)
        sources.append(
            {
                "tool_name": tool_name,
                "fact_type": payload.get("fact_type") or presentation.get("fact_type"),
                "presentation": presentation,
                "items": items,
                "items_truncated": bool(payload.get("items_truncated")),
            }
        )
    return sources


def build_fact_set(
    facts: dict[str, dict[str, Any]],
    plan: AnalysisPlan,
) -> dict[str, Any]:
    sources = _sources_from_facts(facts)
    identity = json.dumps(
        [
            {
                "tool": source["tool_name"],
                "ids": [str(item.get("id") or "") for item in source["items"]],
            }
            for source in sources
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "id": f"monitor-facts-{hashlib.sha256(identity.encode()).hexdigest()[:12]}",
        "time_range": plan.time_range.as_dict(),
        "sources": sources,
    }


def _prior_sources(prior_fact_set: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(prior_fact_set, dict):
        return []
    return [
        source
        for source in prior_fact_set.get("sources") or []
        if isinstance(source, dict) and source.get("items")
    ]


def _sources_for_requested_view(
    sources: list[dict[str, Any]], requested_view: str
) -> list[dict[str, Any]]:
    """用工具自描述词汇选择事实类型，不维护问题到 Intent 的分支矩阵。"""
    normalized_view = re.sub(r"\s+", "", requested_view).lower()
    matched = []
    for source in sources:
        presentation = source.get("presentation") or {}
        title = str(presentation.get("title") or "").removesuffix("明细")
        terms = [title, *(presentation.get("view_terms") or [])]
        if any(
            (term_text := re.sub(r"\s+", "", str(term)).lower()) and term_text in normalized_view
            for term in terms
        ):
            matched.append(source)
    return matched


def render_fact_answer(
    *,
    question: str,
    plan: AnalysisPlan,
    conclusion: AnalysisConclusion,
    facts: dict[str, dict[str, Any]],
    prior_fact_set: dict[str, Any] | None = None,
) -> str | None:
    """按真实工具事实渲染通用回答，不依赖固定 Intent 或问句模板。"""
    sources = _sources_from_facts(facts)
    using_prior = False
    if not sources and references_prior_facts(question):
        sources = _prior_sources(prior_fact_set)
        using_prior = bool(sources)
    if not sources:
        return None
    requested_sources = _sources_for_requested_view(
        sources,
        plan.requested_view or question,
    )
    if requested_sources:
        sources = requested_sources
    # 单一事实类型可以安全地直接展开明细；多类型综合分析仍交给现有确定性
    # 综合报告，避免把平台健康问题退化成多张缺少业务判断的原始表格。
    if len(sources) > 1:
        return None

    total = sum(len(source["items"]) for source in sources)
    if len(sources) == 1:
        fact_title = str(sources[0]["presentation"].get("title") or "事实明细")
        lead = f"共取得 {total} 条{fact_title.removesuffix('明细')}，具体如下。"
    else:
        lead = f"共取得 {total} 条授权监控事实，已按事实类型列出。"
    lines = [
        "### 查询结果",
        "",
        lead,
        "",
        f"- 时间范围：{_time_description(plan)}",
    ]
    if using_prior:
        lines.append("- 数据来源：上一轮已授权查询结果")

    for source in sources:
        presentation = source.get("presentation") or {}
        columns = [
            column
            for column in presentation.get("columns") or []
            if isinstance(column, dict) and column.get("field") and column.get("label")
        ]
        items = list(source.get("items") or [])
        if not columns:
            continue
        lines.extend(
            [
                "",
                f"### {presentation.get('title') or '事实明细'}",
                "",
                "| " + " | ".join(str(column["label"]) for column in columns) + " |",
                "| " + " | ".join("---" for _ in columns) + " |",
            ]
        )
        for item in items[:20]:
            lines.append(
                "| "
                + " | ".join(
                    _display_value(str(column["field"]), item.get(column["field"]))
                    for column in columns
                )
                + " |"
            )
        if source.get("items_truncated") or len(items) > 20:
            lines.extend(["", "- 明细数量较多，当前仅展示前 20 条。"])

    conclusion_names = {
        AnalysisConclusion.NORMAL: "现有事实未显示需要关注的异常。",
        AnalysisConclusion.WARNING: "现有事实中存在需要关注的情况。",
        AnalysisConclusion.ABNORMAL: "现有事实中存在异常或严重活动告警。",
        AnalysisConclusion.UNKNOWN: "以上仅展示查询事实，现有证据不足以形成整体状态判断。",
    }
    lines.extend(["", "### 事实说明", "", conclusion_names[conclusion]])
    return "\n".join(lines)


__all__ = (
    "TOOL_PRESENTATIONS",
    "build_fact_set",
    "presentation_for_tool",
    "references_prior_facts",
    "render_fact_answer",
)
