from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.schemas.monitoring import (
    CausalAssessment,
    InvestigationAnalysis,
    InvestigationFinding,
    InvestigationObservation,
    InvestigationRelation,
)

from .models import AnalysisConclusion, AnalysisIntent, AnalysisPlan

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
            {"field": "alert_info", "label": "告警信息"},
            {"field": "status_detail", "label": "状态详情"},
            {"field": "time_detail", "label": "时间信息"},
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
    "get_alert_details": {
        "fact_type": "alert",
        "title": "告警明细",
        "view_terms": ["告警", "明细", "分别", "具体"],
        "columns": [
            {"field": "alert_info", "label": "告警信息"},
            {"field": "status_detail", "label": "状态详情"},
            {"field": "time_detail", "label": "时间信息"},
        ],
    },
    "correlate_alerts": {
        "fact_type": "alert_correlation",
        "title": "告警关联",
        "view_terms": ["重复", "关联", "同一", "相同"],
        "columns": [
            {"field": "title", "label": "告警分组"},
            {"field": "member_count", "label": "告警数量"},
            {"field": "status_name", "label": "关联判断"},
            {"field": "summary", "label": "判断依据"},
            {"field": "judgment_boundary", "label": "判断边界"},
        ],
    },
    "query_metric_series": {
        "fact_type": "metric_series",
        "title": "指标趋势",
        "view_terms": ["趋势", "变化", "前后", "指标"],
        "columns": [
            {"field": "title", "label": "指标名称"},
            {"field": "summary", "label": "指标结果"},
            {"field": "window_end", "label": "统计时间"},
            {"field": "assessment_status", "label": "评估状态"},
        ],
    },
    "query_resource_timeline": {
        "fact_type": "timeline",
        "title": "资源时间线",
        "view_terms": ["时间线", "发生了什么", "资源", "链路"],
        "columns": [
            {"field": "occurred_at", "label": "发生时间"},
            {"field": "title", "label": "事件类型"},
            {"field": "status", "label": "事件状态"},
            {"field": "summary", "label": "事件摘要"},
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
    if field in {"current_value", "threshold"} and isinstance(value, (int, float)):
        if abs(value) < 0.005:
            value = 0
        return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    text = str(value)
    if field in {"status", "assessment_status"}:
        text = _STATUS_NAMES.get(text.lower(), text)
    elif field == "severity":
        text = _SEVERITY_NAMES.get(text.lower(), text)
    elif field == "resource_type":
        text = _RESOURCE_TYPE_NAMES.get(text.lower(), text)
    return text.replace("|", "｜").replace("\n", " ").strip()[:500] or "—"


def _duration_description(value: Any) -> str:
    try:
        seconds = max(0, int(value))
    except (TypeError, ValueError):
        return "暂无"
    if seconds < 60:
        return f"{seconds}秒"
    if seconds < 3600:
        return f"{seconds // 60}分钟"
    if seconds < 86400:
        return f"{seconds // 3600}小时"
    return f"{seconds // 86400}天"


def _fact_display_value(source: dict[str, Any], item: dict[str, Any], field: str) -> str:
    """兼容已注册工具只返回原子字段的情况，展示层不要求工具拼接文案。"""
    value = item.get(field)
    if value not in (None, "") or source.get("fact_type") != "alert":
        return _display_value(field, value)
    if field == "alert_info":
        title = _display_value("title", item.get("alert_title") or item.get("title"))
        severity = _display_value("severity", item.get("severity_name") or item.get("severity"))
        domain = _display_value("monitor_domain_name", item.get("monitor_domain_name"))
        resource = _display_value("resource_name", item.get("resource_name"))
        return f"{title}；{severity} · {domain}；资源：{resource}"
    if field == "status_detail":
        status = _display_value("status", item.get("status_name") or item.get("status"))
        current = _display_value("current_value", item.get("current_value"))
        threshold = _display_value("threshold", item.get("threshold"))
        samples = _display_value("sample_count", item.get("sample_count"))
        return f"{status}；当前值：{current}；阈值：{threshold}；样本：{samples}"
    if field == "time_detail":
        last_fired = _display_value("last_fired_at", item.get("last_fired_at"))
        first_fired = _display_value("first_fired_at", item.get("first_fired_at"))
        duration = _duration_description(item.get("duration_seconds"))
        firing_count = _display_value("firing_count", item.get("firing_count"))
        acknowledged = _display_value("acknowledged_by_name", item.get("acknowledged_by_name"))
        return (
            f"最近：{last_fired}；首次：{first_fired}；持续：{duration}；"
            f"触发：{firing_count} 次；确认：{acknowledged}"
        )
    return "—"


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


def _selected_sources(
    *,
    question: str,
    plan: AnalysisPlan,
    facts: dict[str, dict[str, Any]],
    prior_fact_set: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], bool]:
    """统一确定本轮应展示的事实，避免 Markdown 与结构化视图选择不一致。"""
    sources = _sources_from_facts(facts)
    using_prior = False
    if not sources and references_prior_facts(question):
        sources = _prior_sources(prior_fact_set)
        using_prior = bool(sources)
    requested_sources = _sources_for_requested_view(
        sources,
        plan.requested_view or question,
    )
    selected = requested_sources or sources
    if any(source.get("tool_name") == "get_alert_details" for source in selected):
        selected = [source for source in selected if source.get("tool_name") != "query_alerts"]
    return selected, using_prior


def _conclusion_description(conclusion: AnalysisConclusion) -> str:
    descriptions = {
        AnalysisConclusion.NORMAL: "现有事实未显示需要关注的异常。",
        AnalysisConclusion.WARNING: "现有事实中存在需要关注的情况。",
        AnalysisConclusion.ABNORMAL: "现有事实中存在异常或严重活动告警。",
        AnalysisConclusion.UNKNOWN: "以上仅展示查询事实，现有证据不足以形成整体状态判断。",
    }
    return descriptions[conclusion]


def _fact_ids(items: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(item.get("id") or "") for item in items if item.get("id")))


def _alert_items(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    detailed = next(
        (source for source in sources if source.get("tool_name") == "get_alert_details"),
        None,
    )
    if detailed is not None:
        return list(detailed.get("items") or [])
    return [
        item
        for source in sources
        if source.get("fact_type") == "alert"
        for item in source.get("items") or []
    ]


def _threshold_relation(current: Any, threshold: Any) -> str:
    try:
        current_number = Decimal(str(current))
        threshold_number = Decimal(str(threshold))
    except Exception:
        return "达到规则触发条件"
    if current_number < threshold_number:
        return "低于"
    if current_number > threshold_number:
        return "高于"
    return "达到"


def _direct_cause_findings(alerts: list[dict[str, Any]]) -> list[InvestigationFinding]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in alerts:
        key = (
            str(item.get("metric_name") or item.get("title") or "监控指标"),
            str(item.get("current_value")),
            str(item.get("threshold")),
            str(item.get("sample_count") or 0),
        )
        groups.setdefault(key, []).append(item)
    findings = []
    for (metric_name, _current, _threshold, sample_count), items in groups.items():
        relation = _threshold_relation(items[0].get("current_value"), items[0].get("threshold"))
        scopes = list(
            dict.fromkeys(str(item.get("resource_name") or "当前授权范围") for item in items)
        )
        scope_text = "、".join(scopes)
        findings.append(
            InvestigationFinding(
                finding_type="threshold_breach",
                title=f"{metric_name}触发告警",
                summary=(
                    f"{scope_text}的{metric_name}当前值为"
                    f"{_display_value('current_value', items[0].get('current_value'))}，"
                    f"{relation}阈值{_display_value('threshold', items[0].get('threshold'))}，"
                    f"统计样本为{sample_count}，因此满足当前告警规则的直接触发条件。"
                ),
                status="confirmed",
                subject_refs=_fact_ids(items),
                evidence_refs=_fact_ids(items),
                confidence=1.0,
            )
        )
    return findings


def _relation_findings(
    sources: list[dict[str, Any]], alerts: list[dict[str, Any]]
) -> list[InvestigationRelation]:
    relations = []
    for source in sources:
        if source.get("fact_type") != "alert_correlation":
            continue
        for item in source.get("items") or []:
            if int(item.get("member_count") or 0) < 2:
                continue
            relations.append(
                InvestigationRelation(
                    relation_type="alert_correlation",
                    title=str(item.get("title") or "告警关联"),
                    summary=(
                        f"{item.get('summary') or '告警存在共同字段'}；"
                        f"{item.get('judgment_boundary') or '当前只能确认关联，不能直接认定因果。'}"
                    ),
                    status=(
                        "suspected"
                        if item.get("status") in {"likely_duplicate", "related"}
                        else "unconfirmed"
                    ),
                    subject_refs=[str(value) for value in item.get("member_ids") or []],
                    evidence_refs=_fact_ids([item]),
                )
            )

    # 不硬编码指标名称：同一范围、样本量一致且触发时间接近，只标记为同批次候选。
    seen_pairs: set[tuple[str, str]] = set()
    for index, left in enumerate(alerts):
        for right in alerts[index + 1 :]:
            if left.get("metric_name") == right.get("metric_name"):
                continue
            if left.get("scope_key") != right.get("scope_key"):
                continue
            if left.get("sample_count") != right.get("sample_count"):
                continue
            left_time = left.get("last_fired_at") or left.get("occurred_at")
            right_time = right.get("last_fired_at") or right.get("occurred_at")
            if not isinstance(left_time, datetime) or not isinstance(right_time, datetime):
                continue
            if abs((left_time - right_time).total_seconds()) > 300:
                continue
            pair = tuple(sorted((str(left.get("id") or ""), str(right.get("id") or ""))))
            if not all(pair) or pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            relations.append(
                InvestigationRelation(
                    relation_type="same_sample_window",
                    title="同一统计批次候选",
                    summary=(
                        f"{left.get('metric_name') or '监控指标'}与"
                        f"{right.get('metric_name') or '监控指标'}的统计范围、样本量一致，"
                        "并且触发时间接近，"
                        "可能来自同一批业务请求，但当前证据不足以认定底层因果。"
                    ),
                    status="suspected",
                    subject_refs=list(pair),
                    evidence_refs=list(pair),
                )
            )
    return relations


def build_investigation_analysis(
    *,
    question: str,
    plan: AnalysisPlan,
    facts: dict[str, dict[str, Any]],
    prior_fact_set: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将工具事实统一收敛为开放调查结构，供模型成功和降级路径共同使用。"""
    sources = _sources_from_facts(facts)
    if not sources and references_prior_facts(question):
        sources = _prior_sources(prior_fact_set)
    alerts = _alert_items(sources)
    observations = [
        InvestigationObservation(
            observation_type=str(source.get("fact_type") or "fact"),
            title=str((source.get("presentation") or {}).get("title") or "监控事实"),
            summary=f"已取得{len(source.get('items') or [])}条授权事实。",
            subject_refs=_fact_ids(list(source.get("items") or [])),
            evidence_refs=_fact_ids(list(source.get("items") or [])),
        )
        for source in sources
    ]
    findings = (
        _direct_cause_findings(alerts) if plan.intent == AnalysisIntent.INCIDENT_CAUSE else []
    )
    relations = _relation_findings(sources, alerts)
    timeline_items = [
        item
        for source in sources
        if source.get("fact_type") in {"timeline", "event", "task"}
        for item in source.get("items") or []
    ]
    unknowns = []
    next_checks = []
    if plan.intent == AnalysisIntent.INCIDENT_CAUSE:
        unknowns.append(
            "当前证据可以确认规则阈值的直接触发原因，但不能仅凭指标和时间相关性认定底层根因。"
        )
        if any(
            item.get("status") in {"firing", "acknowledged"}
            and isinstance(item.get("first_fired_at"), datetime)
            and item["first_fired_at"] < plan.time_range.start
            for item in alerts
        ):
            unknowns.append(
                "本轮时间范围包含当前仍活动的告警，部分告警首次触发时间早于窗口开始，"
                "不能将其表述为本窗口内新产生。"
            )
        if not timeline_items:
            unknowns.append("当前未取得可关联的资源时间线、运行事件或任务事实。")
        next_checks.append("按告警对应的时间、资源或 Trace 继续核查检索、模型及外部依赖事件。")
    evidence_refs = list(
        dict.fromkeys(
            reference for observation in observations for reference in observation.evidence_refs
        )
    )
    root_cause_status = (
        "unconfirmed" if plan.intent == AnalysisIntent.INCIDENT_CAUSE else "not_applicable"
    )
    root_cause_summary = (
        "现有事实只能确认指标越过规则阈值及告警之间的关联，尚无充分证据定位到底层组件根因。"
        if plan.intent == AnalysisIntent.INCIDENT_CAUSE
        else "本轮分析目标不要求形成因果结论。"
    )
    analysis = InvestigationAnalysis(
        analysis_goal=plan.goal or question.strip(),
        subject_refs=_fact_ids(alerts) or evidence_refs,
        observations=observations,
        findings=findings,
        relations=relations,
        causal_assessment=CausalAssessment(
            direct_causes=findings,
            correlated_factors=relations,
            root_cause_status=root_cause_status,
            root_cause_summary=root_cause_summary,
        ),
        unknowns=unknowns,
        next_checks=next_checks,
        evidence_refs=evidence_refs,
    )
    return analysis.model_dump(mode="json")


def render_investigation_answer(
    analysis: dict[str, Any],
    plan: AnalysisPlan,
    conclusion: AnalysisConclusion,
) -> str | None:
    if plan.intent != AnalysisIntent.INCIDENT_CAUSE:
        return None
    direct_causes = list((analysis.get("causal_assessment") or {}).get("direct_causes") or [])
    if not direct_causes:
        return None
    lines = [
        "### 原因结论",
        "",
        f"当前可以确认 {len(direct_causes)} 组规则阈值直接触发原因。"
        "告警之间存在的指标或时间关联只能作为调查线索，不能直接等同于底层根因。",
        "",
        f"- 时间范围：{_time_description(plan)}",
        f"- 状态判断：{_conclusion_description(conclusion)}",
        "",
        "### 直接触发原因",
        "",
    ]
    lines.extend(f"{index}. {item['summary']}" for index, item in enumerate(direct_causes, 1))
    relations = list(analysis.get("relations") or [])
    lines.extend(["", "### 关联判断", ""])
    if relations:
        lines.extend(f"- {item['summary']}" for item in relations)
    else:
        lines.append("- 当前没有足够事实确认这些告警是否来自同一统计批次或同一底层故障。")
    causal = analysis.get("causal_assessment") or {}
    lines.extend(
        [
            "",
            "### 底层根因",
            "",
            str(causal.get("root_cause_summary") or "现有证据不足，暂时无法确认底层根因。"),
            "",
            "### 判断边界",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in analysis.get("unknowns") or [])
    if analysis.get("next_checks"):
        lines.extend(["", "### 后续检查", ""])
        lines.extend(f"- {item}" for item in analysis["next_checks"])
    return "\n".join(lines)


def build_fact_presentation(
    *,
    question: str,
    plan: AnalysisPlan,
    conclusion: AnalysisConclusion,
    facts: dict[str, dict[str, Any]],
    prior_fact_set: dict[str, Any] | None = None,
    investigation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """为 Web 等富客户端提供结构化视图提示；完整 Markdown 回答仍保留。"""
    sources, using_prior = _selected_sources(
        question=question,
        plan=plan,
        facts=facts,
        prior_fact_set=prior_fact_set,
    )
    alert_sources = [source for source in sources if source.get("fact_type") == "alert"]
    correlation_sources = [
        source for source in sources if source.get("fact_type") == "alert_correlation"
    ]
    if not alert_sources:
        return {}
    alert_ids = {
        str(item.get("id") or "") for source in alert_sources for item in source.get("items") or []
    }
    total = len(alert_ids)
    lines = [
        "### 查询结果",
        "",
        f"共取得 {total} 条告警，具体如下。",
        "",
        f"- 时间范围：{_time_description(plan)}",
    ]
    if using_prior:
        lines.append("- 数据来源：上一轮已授权查询结果")
    if correlation_sources:
        groups = [item for source in correlation_sources for item in source.get("items") or []]
        likely = sum(item.get("status") == "likely_duplicate" for item in groups)
        lines.extend(
            [
                "",
                "### 关联判断",
                "",
                f"共形成 {len(groups)} 个告警关联分组，其中 {likely} 个分组高度相似。",
                "字段和时间相似只能证明告警高度相关，不能单独证明数据库重复写入。",
            ]
        )
    lines.extend(["", "### 事实说明", "", _conclusion_description(conclusion)])
    if plan.intent == AnalysisIntent.INCIDENT_CAUSE and investigation:
        summary = render_investigation_answer(investigation, plan, conclusion)
        return {
            "type": "composite",
            "fact_type": "alert",
            "title": "原因分析",
            "summary_markdown": summary,
            "blocks": [
                {"type": "conclusion", "title": "原因结论"},
                {"type": "cause_findings", "title": "直接触发原因"},
                {"type": "relation_groups", "title": "关联判断"},
                {"type": "limitations", "title": "判断边界"},
                {"type": "next_checks", "title": "后续检查"},
                {
                    "type": "alert_list",
                    "title": "告警明细",
                    "source_tools": ["get_alert_details", "query_alerts"],
                    "fact_types": ["alert"],
                },
            ],
        }
    return {
        "type": "alert_list",
        "fact_type": "alert",
        "title": "告警明细",
        "summary_markdown": "\n".join(lines),
    }


def render_fact_answer(
    *,
    question: str,
    plan: AnalysisPlan,
    conclusion: AnalysisConclusion,
    facts: dict[str, dict[str, Any]],
    prior_fact_set: dict[str, Any] | None = None,
    investigation: dict[str, Any] | None = None,
) -> str | None:
    """按真实工具事实渲染通用回答，不依赖固定 Intent 或问句模板。"""
    investigation_answer = render_investigation_answer(investigation or {}, plan, conclusion)
    if investigation_answer:
        return investigation_answer
    sources, using_prior = _selected_sources(
        question=question,
        plan=plan,
        facts=facts,
        prior_fact_set=prior_fact_set,
    )
    if not sources:
        return None
    specialized_tools = {
        "get_alert_details",
        "correlate_alerts",
        "query_metric_series",
        "query_resource_timeline",
    }
    if len(sources) > 1 and not any(
        source.get("tool_name") in specialized_tools for source in sources
    ):
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
                    _fact_display_value(source, item, str(column["field"])) for column in columns
                )
                + " |"
            )
        if source.get("items_truncated") or len(items) > 20:
            lines.extend(["", "- 明细数量较多，当前仅展示前 20 条。"])

    lines.extend(["", "### 事实说明", "", _conclusion_description(conclusion)])
    return "\n".join(lines)


__all__ = (
    "TOOL_PRESENTATIONS",
    "build_fact_presentation",
    "build_fact_set",
    "build_investigation_analysis",
    "presentation_for_tool",
    "references_prior_facts",
    "render_investigation_answer",
    "render_fact_answer",
)
