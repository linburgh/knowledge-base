from __future__ import annotations

from time import perf_counter
from typing import Any

from app.core.common import utils
from app.core.common.log import LOG
from app.schemas.monitoring import MonitoringContext, MonitoringOverviewResult, MonitoringResult

from .answering import (
    DeterministicMarkdownAnswerComposer,
    MonitoringAnswerComposer,
)
from .models import AnalysisConclusion, AnalysisIntent, AnalysisPlan
from .planner import MonitoringPlanner, build_monitoring_planner
from .policies import redact_context, validate_context
from .runtime import MonitoringRuntime
from .skills import load_skill
from .tools.registry import MonitoringToolRegistry

IDENTITY_ANSWER = """### 你好，我是自主监控智能分析助手

你可以把我当作运行状态排查搭档。我会在你的权限范围内，结合告警、指标、事件、任务和链路证据，帮你判断发生了什么、可能影响哪些服务，以及接下来值得检查什么。

你可以直接问我：“为什么会触发这条告警？”“当前影响了哪些资源？”“有哪些直接证据？”或者“下一步应该检查什么？”

为了保证操作安全，我只负责分析并提供可追溯的建议，不会替你修改配置、重试任务或执行处置。"""

AGENT_DISPLAY_NAME = "自主监控智能体"

_FAILURE_STATUSES = {"critical", "failed", "failure", "error", "unavailable", "abnormal"}
_WARNING_STATUSES = {"warning", "degraded", "stale", "partial", "insufficient"}
_ACTIVE_ALERT_STATUSES = {"firing", "acknowledged"}
_TOOL_DISPLAY_NAMES = {
    "query_health_snapshots": "健康状态",
    "query_alerts": "告警信息",
    "query_metrics": "运行指标",
    "query_events": "运行事件",
    "query_tasks": "任务信息",
}


def _serialize_evidence(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    for key in ("occurred_at", "expires_at"):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def _legacy_facts(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidence = [_serialize_evidence(item) for item in context.get("evidence", [])]
    alerts = []
    for item in context.get("alerts", []):
        alerts.append(
            {
                "id": f"alert-{item.get('id', len(alerts) + 1)}",
                "evidence_type": "alert",
                "evidence_type_name": "告警信息",
                "title": item.get("alert_title") or "监控告警",
                "summary": str(item.get("analysis_summary") or "已关联监控告警"),
                "evidence_level": "direct",
                "evidence_level_name": "直接证据",
                "target_id": str(item.get("id") or ""),
                "status": str(item.get("status") or "firing"),
                "severity": str(item.get("severity") or "warning"),
            }
        )
    return {
        "query_alerts": {"items": alerts, "data_status": "ready" if alerts else "empty"},
        "query_events": {"items": evidence, "data_status": "ready" if evidence else "empty"},
    }


def _fact_items(facts: dict[str, dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return list((facts.get(name) or {}).get("items") or [])


def _assess_facts(
    plan: AnalysisPlan,
    facts: dict[str, dict[str, Any]],
    failed_tools: list[str],
) -> tuple[AnalysisConclusion, str, list[str]]:
    health = _fact_items(facts, "query_health_snapshots")
    alerts = _fact_items(facts, "query_alerts")
    metrics = _fact_items(facts, "query_metrics")
    events = _fact_items(facts, "query_events")
    tasks = _fact_items(facts, "query_tasks")
    limitations = [f"{_TOOL_DISPLAY_NAMES.get(name, '监控数据')}查询失败" for name in failed_tools]
    limitations.extend(plan.uncertainties)
    if plan.time_range.limitation:
        limitations.append(plan.time_range.limitation)

    active_critical = any(
        str(item.get("status")) in _ACTIVE_ALERT_STATUSES
        and str(item.get("severity")) == "critical"
        for item in alerts
    )
    health_failed = any(str(item.get("status")) in _FAILURE_STATUSES for item in health)
    metric_failed = any(str(item.get("assessment_status")) in _FAILURE_STATUSES for item in metrics)
    if active_critical or health_failed or metric_failed:
        return (
            AnalysisConclusion.ABNORMAL,
            "complete" if not failed_tools else "partial",
            limitations,
        )

    all_items = health + alerts + metrics + events + tasks
    if not all_items:
        limitations.append("指定时间范围内没有可用于判断的监控事实")
        return AnalysisConclusion.UNKNOWN, "empty", limitations
    if failed_tools:
        return AnalysisConclusion.UNKNOWN, "partial", limitations
    if plan.intent == AnalysisIntent.PLATFORM_HEALTH and not health and not metrics:
        limitations.append("缺少健康快照和核心指标，不能仅根据告警或事件判断平台正常")
        return AnalysisConclusion.UNKNOWN, "partial", limitations

    has_warning = (
        bool(alerts)
        or any(
            str(item.get("status")) in _WARNING_STATUSES | _FAILURE_STATUSES
            for item in health + events + tasks
        )
        or any(str(item.get("assessment_status")) in _WARNING_STATUSES for item in metrics)
    )
    if has_warning:
        return AnalysisConclusion.WARNING, "complete", limitations
    return AnalysisConclusion.NORMAL, "complete", limitations


def _time_description(plan: AnalysisPlan) -> str:
    start = plan.time_range.start.strftime("%Y年%m月%d日 %H:%M:%S")
    end = plan.time_range.end.strftime("%Y年%m月%d日 %H:%M:%S")
    return f"{plan.time_range.label}（{start}—{end}，中国标准时间）"


def _format_report(
    *,
    conclusion: str,
    basis: list[str],
    limitations: list[str] | None = None,
    suggestions: list[str] | None = None,
) -> str:
    sections = ["### 分析结论", "", f"**{conclusion}**", "", "### 分析依据", ""]
    sections.extend(f"- {item}" for item in basis)
    if limitations:
        sections.extend(["", "### 判断边界", ""])
        sections.extend(f"- {item}" for item in dict.fromkeys(limitations))
    if suggestions:
        sections.extend(["", "### 处理建议", ""])
        sections.extend(f"- {item}" for item in suggestions)
    return "\n".join(sections)


def _build_answer(
    plan: AnalysisPlan,
    conclusion: AnalysisConclusion,
    facts: dict[str, dict[str, Any]],
    limitations: list[str],
) -> str:
    time_text = _time_description(plan)
    health = _fact_items(facts, "query_health_snapshots")
    alerts = _fact_items(facts, "query_alerts")
    metrics = _fact_items(facts, "query_metrics")
    events = _fact_items(facts, "query_events")
    tasks = _fact_items(facts, "query_tasks")
    active_alerts = [item for item in alerts if item.get("status") in _ACTIVE_ALERT_STATUSES]
    resolved_alerts = [item for item in alerts if item.get("status") in {"resolved", "closed"}]
    facts_text = (
        f"已检查 {len(health)} 条健康状态、{len(metrics)} 条指标、{len(alerts)} 条告警、"
        f"{len(events)} 条事件和 {len(tasks)} 条任务事实"
    )

    if plan.intent == AnalysisIntent.PLATFORM_HEALTH:
        labels = {
            AnalysisConclusion.NORMAL: "平台整体运行正常",
            AnalysisConclusion.WARNING: "平台运行存在需要关注的情况",
            AnalysisConclusion.ABNORMAL: "平台运行存在异常",
            AnalysisConclusion.UNKNOWN: "现有证据不足，无法判断平台是否正常",
        }
        suggestions = {
            AnalysisConclusion.NORMAL: ["建议继续观察核心指标趋势和新增告警。"],
            AnalysisConclusion.WARNING: ["建议优先核查告警关联资源和异常时间段的指标变化。"],
            AnalysisConclusion.ABNORMAL: [
                "建议立即核查严重告警、失败指标及关联事件，并由人工确认处置。"
            ],
            AnalysisConclusion.UNKNOWN: ["建议先补齐健康状态和核心指标，再判断平台运行情况。"],
        }
        lines = [
            f"> **{labels[conclusion]}。**",
            ">",
            f"> 分析时段：{time_text}",
            "",
            "### 运行概览",
            "",
            "| 检查维度 | 数据量 | 当前判断 |",
            "| --- | ---: | --- |",
            f"| 健康状态 | {len(health)} 条 | {'已覆盖' if health else '暂无数据'} |",
            f"| 运行指标 | {len(metrics)} 条 | {'已覆盖' if metrics else '暂无数据'} |",
            f"| 告警信息 | {len(alerts)} 条 | 未恢复 {len(active_alerts)} 条，"
            f"已恢复或关闭 {len(resolved_alerts)} 条 |",
            f"| 运行事件 | {len(events)} 条 | 已纳入时间窗口分析 |",
            f"| 任务信息 | {len(tasks)} 条 | {'已覆盖' if tasks else '暂无数据'} |",
        ]
        if limitations:
            lines.extend(["", "### 需要说明", ""])
            lines.extend(f"- {item}" for item in dict.fromkeys(limitations))
        lines.extend(["", "### 后续关注", ""])
        lines.extend(f"1. {item}" for item in suggestions[conclusion])
        return "\n".join(lines)
    if plan.intent == AnalysisIntent.INCIDENT_CAUSE:
        return _format_report(
            conclusion="当前证据可用于定位时间关联，但不足以直接认定异常根因。",
            basis=[
                f"时间范围：{time_text}",
                f"关联事实：告警 {len(alerts)} 条、事件 {len(events)} 条、"
                f"指标 {len(metrics)} 条、任务 {len(tasks)} 条",
            ],
            limitations=["时间关联不等同于因果关系。", *limitations],
            suggestions=["建议沿严重告警、异常指标、关联事件和任务链路继续交叉核查。"],
        ).strip()
    if plan.intent == AnalysisIntent.IMPACT_SCOPE:
        resources = sorted(
            {str(item.get("resource_name")) for item in alerts if item.get("resource_name")}
        )
        if resources:
            resource_text = "、".join(resources)
        elif alerts:
            resource_text = f"已关联 {len(alerts)} 条告警，具体资源名称请查看证据明细"
        else:
            resource_text = "暂无可确认的受影响资源"
        return _format_report(
            conclusion=f"当前可确认的影响范围：{resource_text}。",
            basis=[f"时间范围：{time_text}", f"关联告警：{len(alerts)} 条"],
            limitations=limitations,
            suggestions=["建议结合资源依赖关系和同时间窗口事件确认是否存在间接影响。"],
        ).strip()
    if plan.intent == AnalysisIntent.EVIDENCE_REVIEW:
        evidence_count = len(health + alerts + metrics + events + tasks)
        return _format_report(
            conclusion=f"当前共取得 {evidence_count} 条可追溯的授权证据。",
            basis=[f"时间范围：{time_text}", f"数据检查：{facts_text}"],
            limitations=limitations,
            suggestions=["建议优先查看直接证据，再核对关联证据和背景证据。"],
        ).strip()
    if plan.intent == AnalysisIntent.NEXT_ACTION:
        action = (
            "建议优先核查严重告警对应资源、失败指标及同时间窗口的事件和任务链路"
            if conclusion in {AnalysisConclusion.ABNORMAL, AnalysisConclusion.WARNING}
            else "建议先补齐健康快照和核心指标，再决定是否需要处置"
        )
        return _format_report(
            conclusion="已根据当前授权证据形成后续检查方向。",
            basis=[f"时间范围：{time_text}", f"数据检查：{facts_text}"],
            limitations=limitations,
            suggestions=[f"{action}。", "所有处置均需人工确认。"],
        ).strip()
    if plan.intent == AnalysisIntent.TASK_DIAGNOSIS:
        failed = [item for item in tasks if str(item.get("status")) in _FAILURE_STATUSES]
        return _format_report(
            conclusion=f"共发现 {len(tasks)} 条任务事实，其中失败或异常 {len(failed)} 条。",
            basis=[f"时间范围：{time_text}", f"任务检查：{len(tasks)} 条"],
            limitations=limitations,
            suggestions=["建议从失败任务的事件记录和链路信息继续定位。"],
        ).strip()
    conclusion_names = {
        AnalysisConclusion.NORMAL: "运行正常",
        AnalysisConclusion.WARNING: "存在需要关注的情况",
        AnalysisConclusion.ABNORMAL: "存在异常",
        AnalysisConclusion.UNKNOWN: "证据不足，暂时无法判断",
    }
    return _format_report(
        conclusion=f"综合结论为{conclusion_names[conclusion]}。",
        basis=[f"时间范围：{time_text}", f"数据检查：{facts_text}"],
        limitations=limitations,
        suggestions=["建议结合证据明细继续核查需要关注的资源和时间点。"],
    ).strip()


class MonitoringAgent:
    """自主监控 Agent：分析总览与分析对话均由此入口负责。"""

    def __init__(
        self,
        *,
        runtime: MonitoringRuntime | None = None,
        tools: MonitoringToolRegistry | None = None,
        planner: MonitoringPlanner | None = None,
        answer_composer: MonitoringAnswerComposer | None = None,
    ) -> None:
        self.runtime = runtime or MonitoringRuntime()
        self.tools = tools or MonitoringToolRegistry()
        self.planner = planner
        self.answer_composer = answer_composer or DeterministicMarkdownAnswerComposer()

    async def build_overview(
        self, *, context: dict[str, Any] | MonitoringContext
    ) -> dict[str, Any]:
        """把授权范围内的结构化事实整理为可验证的分析总览。"""
        if isinstance(context, MonitoringContext):
            context = context.model_dump()
        validate_context(context)
        safe_context = redact_context(context)

        async def execute():
            alerts = safe_context.get("alerts", [])
            evidence = safe_context.get("evidence", [])
            impacts = safe_context.get("impacts", [])
            timeline = safe_context.get("timeline", [])
            suggestions = safe_context.get("suggestions", [])
            presentation_state = safe_context.get("presentation_state", "unknown")
            presentation_state_name = safe_context.get("presentation_state_name", "证据不足")
            impact_overview = safe_context.get("impact_overview") or {
                "status": "unknown",
                "status_name": "无法判断",
                "title": "影响范围无法判断",
                "detail": "当前缺少足够的授权运行事实，暂时无法判断影响范围。",
            }
            action_overview = safe_context.get("action_overview") or {
                "status": "supplement",
                "status_name": "补充证据",
                "title": "需要补充运行证据",
                "detail": "请先核查数据采集和指标聚合状态，再重新分析。",
            }
            checks = list(safe_context.get("checks") or [])
            judgment_boundary = str(
                safe_context.get("judgment_boundary")
                or "本次报告仅覆盖当前授权范围和分析时间窗口内的运行事实。"
            )
            evidence_sources = {
                str(item.get("evidence_type") or "event")
                for item in evidence
                if isinstance(item, dict)
            }
            confidence = min(95, 55 + len(evidence_sources) * 8 + min(len(evidence), 8) * 2)
            first_alert = alerts[0] if alerts else {}
            has_evidence = bool(evidence)
            conclusion_by_state = {
                "normal": "当前平台运行正常，未发现已确认的业务影响",
                "warning": "当前存在需要继续核查的运行变化",
                "alert": first_alert.get("alert_title") or "当前告警已形成需要核查的业务影响",
                "unknown": "现有证据不足，暂时无法判断平台运行状态和影响范围",
            }
            detail_by_state = {
                "normal": (
                    f"已核查核心指标、活动告警和运行事实，共取得 {len(evidence)} 条授权证据。"
                ),
                "warning": (
                    "当前没有活动告警直接确认影响，"
                    f"已基于 {len(evidence)} 条授权证据形成待验证判断。"
                ),
                "alert": f"分析基于 {len(alerts)} 条活动告警和 {len(evidence)} 条授权证据形成。",
                "unknown": "核心运行事实覆盖不足，不能仅根据没有活动告警推导平台运行正常。",
            }
            return {
                "incident_id": (f"INC-{first_alert.get('id')}" if first_alert else None),
                "analysis_status": "completed" if alerts or has_evidence else "not_required",
                "attention_status": "manual_confirmation" if alerts else "none",
                "confidence": confidence
                if presentation_state != "unknown" and (alerts or has_evidence)
                else None,
                "report_no": str(safe_context.get("report_no") or "AMR-UNAVAILABLE"),
                "generated_at": safe_context.get("generated_at") or utils.utc_now(),
                "conclusion": conclusion_by_state.get(
                    str(presentation_state), conclusion_by_state["unknown"]
                ),
                "conclusion_detail": detail_by_state.get(
                    str(presentation_state), detail_by_state["unknown"]
                ),
                "presentation_state": presentation_state,
                "presentation_state_name": presentation_state_name,
                "impact_overview": impact_overview,
                "action_overview": action_overview,
                "checks": checks,
                "judgment_boundary": judgment_boundary,
                "alerts": alerts,
                "impacts": impacts,
                "evidence": evidence,
                "timeline": timeline,
                "suggestions": suggestions,
                "agent": AGENT_DISPLAY_NAME,
            }

        LOG.info("自主监控Agent overview start")
        result = await self.runtime.run(execute)
        LOG.info("自主监控Agent overview completed status={}", result["analysis_status"])
        return MonitoringOverviewResult.model_validate(result).model_dump(mode="json")

    async def analyze(
        self, *, question: str, context: dict[str, Any] | MonitoringContext
    ) -> dict[str, Any]:
        started_at = perf_counter()
        if isinstance(context, MonitoringContext):
            context = context.model_dump()
        validate_context(context)
        safe_context = redact_context(context)

        async def execute():
            self.runtime.reset()
            _, analysis_skill_ref = load_skill("monitoring-analysis")
            self.runtime.register_skill(analysis_skill_ref)
            planner = self.planner or build_monitoring_planner()
            plan = await self.runtime.invoke_model(
                planner.plan(
                    question,
                    default_time_range=str(safe_context.get("time_range") or "1h"),
                )
            )
            if plan.intent == AnalysisIntent.IDENTITY:
                return {
                    "intent": plan.intent.value,
                    "answer": IDENTITY_ANSWER,
                    "conclusion": AnalysisConclusion.UNKNOWN.value,
                    "data_status": "not_required",
                    "time_range": plan.time_range.as_dict(),
                    "scope": {
                        "type": str(safe_context.get("scope_key") or "platform"),
                        "name": str(safe_context.get("scope_name") or "当前授权范围"),
                    },
                    "status": "completed",
                    "agent": AGENT_DISPLAY_NAME,
                    "evidence": [],
                    "limitations": [],
                    "tool_calls": [],
                    "planning": plan.planning_metadata(),
                    "answering": {"mode": "deterministic", "error": None},
                    "termination_reason": "completed",
                }

            facts: dict[str, dict[str, Any]] = {}
            tool_calls: list[dict[str, Any]] = []
            failed_tools: list[str] = []
            if self.tools.names():
                arguments = {
                    "window_start": plan.time_range.start,
                    "window_end": plan.time_range.end,
                    "scope_key": str(safe_context.get("scope_key") or "platform"),
                }
                for name in plan.tools:
                    tool_started_at = utils.utc_now()
                    tool_started = perf_counter()
                    try:
                        facts[name], trace = await self.runtime.invoke_tool(
                            registry=self.tools,
                            name=name,
                            arguments=arguments,
                            context=safe_context,
                        )
                        tool_calls.append(trace)
                    except Exception as exc:
                        LOG.warning(
                            "自主监控Agent tool failed name={} error={}", name, type(exc).__name__
                        )
                        failed_tools.append(name)
                        tool_calls.append(
                            {
                                "name": name,
                                "status": "failed",
                                "started_at": tool_started_at.isoformat(),
                                "duration_ms": round((perf_counter() - tool_started) * 1000, 2),
                                "error": type(exc).__name__,
                            }
                        )
            else:
                facts = _legacy_facts(safe_context)

            conclusion, data_status, limitations = _assess_facts(plan, facts, failed_tools)
            evidence = []
            seen = set()
            for tool_name in plan.tools:
                for item in _fact_items(facts, tool_name):
                    serialized = _serialize_evidence(item)
                    evidence_id = str(serialized.get("id") or "")
                    if evidence_id in seen:
                        continue
                    seen.add(evidence_id)
                    evidence.append(serialized)
                    if len(evidence) >= self.runtime.max_context_items:
                        break
                if len(evidence) >= self.runtime.max_context_items:
                    break
            all_failed = bool(plan.tools) and len(failed_tools) == len(plan.tools)
            fallback_answer = _build_answer(plan, conclusion, facts, limitations)
            if all_failed:
                answer = _format_report(
                    conclusion="监控数据查询失败，本次暂时无法完成分析。",
                    basis=[f"时间范围：{_time_description(plan)}"],
                    limitations=limitations,
                    suggestions=["原始监控数据仍可查询，请稍后重试。"],
                )
                answering = {"mode": "fallback", "error": "全部查询失败"}
            else:
                _, answer_skill_ref = load_skill("answer-writing")
                self.runtime.register_skill(answer_skill_ref)
                composition = await self.runtime.invoke_model(
                    self.answer_composer.compose(
                        question=question,
                        plan=plan,
                        conclusion=conclusion,
                        facts=facts,
                        limitations=limitations,
                        fallback_markdown=fallback_answer,
                    )
                )
                answer = composition.markdown
                answering = composition.metadata()
            return {
                "intent": plan.intent.value,
                "answer": answer,
                "conclusion": conclusion.value,
                "data_status": data_status,
                "time_range": plan.time_range.as_dict(),
                "scope": {
                    "type": str(safe_context.get("scope_key") or "platform"),
                    "name": str(safe_context.get("scope_name") or "当前授权范围"),
                },
                "status": "failed" if all_failed else "completed",
                "agent": AGENT_DISPLAY_NAME,
                "evidence": evidence,
                "limitations": limitations,
                "tool_calls": tool_calls,
                "planning": plan.planning_metadata(),
                "answering": answering,
                "termination_reason": "tool_failed" if all_failed else "completed",
            }

        LOG.info("自主监控Agent analysis start question_length={}", len(question))
        result = await self.runtime.run(execute)
        result.update(
            {
                "model_call_count": self.runtime.model_call_count,
                "duration_ms": int((perf_counter() - started_at) * 1000),
                "skill_refs": [item.model_dump() for item in self.runtime.skill_refs],
            }
        )
        result = MonitoringResult.model_validate(result).model_dump(mode="json")
        LOG.info("自主监控Agent analysis completed status={}", result["status"])
        return result


__all__ = ("MonitoringAgent",)
