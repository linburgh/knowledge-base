from __future__ import annotations

from typing import Any

from app.core.common.log import LOG

from .policies import redact_context, validate_context
from .runtime import MonitoringRuntime
from .tools.registry import MonitoringToolRegistry


class MonitoringAgent:
    """自主监控 Agent：分析总览与分析对话均由此入口负责。"""

    def __init__(self, *, runtime: MonitoringRuntime | None = None) -> None:
        self.runtime = runtime or MonitoringRuntime()
        self.tools = MonitoringToolRegistry()

    async def build_overview(self, *, context: dict[str, Any]) -> dict[str, Any]:
        """把授权范围内的结构化事实整理为可验证的分析总览。"""
        validate_context(context)
        safe_context = redact_context(context)

        async def execute():
            alerts = safe_context.get("alerts", [])
            evidence = safe_context.get("evidence", [])
            impacts = safe_context.get("impacts", [])
            timeline = safe_context.get("timeline", [])
            suggestions = safe_context.get("suggestions", [])
            evidence_sources = {
                str(item.get("evidence_type") or "event")
                for item in evidence
                if isinstance(item, dict)
            }
            confidence = min(95, 55 + len(evidence_sources) * 8 + min(len(evidence), 8) * 2)
            first_alert = alerts[0] if alerts else {}
            return {
                "incident_id": (
                    f"INC-{first_alert.get('id')}" if first_alert else None
                ),
                "analysis_status": "completed" if alerts else "not_required",
                "attention_status": "manual_confirmation" if alerts else "none",
                "confidence": confidence if alerts else None,
                "conclusion": (
                    first_alert.get("alert_title") or "当前存在需要核查的监控异常"
                    if alerts
                    else "当前范围暂无需要分析的异常"
                ),
                "conclusion_detail": (
                    f"分析基于 {len(alerts)} 条告警、{len(evidence)} 条授权证据形成。"
                    if alerts
                    else "未发现未恢复告警，不生成无证据分析结论。"
                ),
                "alerts": alerts,
                "impacts": impacts,
                "evidence": evidence,
                "timeline": timeline,
                "suggestions": suggestions,
                "agent": "自主监控Agent",
            }

        LOG.info("自主监控Agent overview start")
        result = await self.runtime.run(execute)
        LOG.info("自主监控Agent overview completed status={}", result["analysis_status"])
        return result

    async def analyze(self, *, question: str, context: dict[str, Any]) -> dict[str, Any]:
        validate_context(context)
        safe_context = redact_context(context)

        async def execute():
            alerts = safe_context.get("alerts", [])
            evidence = safe_context.get("evidence", [])
            if alerts:
                answer = f"当前有 {len(alerts)} 条相关告警，已关联 {len(evidence)} 条证据。"
            elif question.strip():
                answer = "当前授权监控上下文未发现关联告警，请结合指标趋势和事件明细继续核查。"
            else:
                answer = "当前授权监控上下文暂无可分析内容。"
            return {
                "answer": answer,
                "status": "completed",
                "agent": "自主监控Agent",
                "evidence": evidence[: self.runtime.max_context_items],
            }

        LOG.info("自主监控Agent analysis start question_length={}", len(question))
        result = await self.runtime.run(execute)
        LOG.info("自主监控Agent analysis completed status={}", result["status"])
        return result


__all__ = ("MonitoringAgent",)
