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
