from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.core.common import utils
from app.core.common.exception import BusiException
from app.core.common.log import LOG
from app.schemas.agent import AgentSkillRef

from .policies import authorize_tool
from .tools.registry import MonitoringToolRegistry


class MonitoringAgentError(BusiException):
    code = "MONITORING_AGENT_ERROR"


class MonitoringBudgetExceeded(MonitoringAgentError):
    code = "MONITORING_BUDGET_EXCEEDED"


class MonitoringCancelled(MonitoringAgentError):
    code = "MONITORING_CANCELLED"


@dataclass
class MonitoringRuntime:
    timeout_seconds: float = 15.0
    max_context_items: int = 50
    max_steps: int = 8
    max_tool_calls: int = 5
    max_model_calls: int = 3
    tool_timeout_seconds: float = 5.0
    max_retries: int = 1
    cancel_check: Callable[[], bool | Awaitable[bool]] | None = None
    tool_call_count: int = 0
    model_call_count: int = 0
    step_count: int = 0
    stop_reason: str = ""
    skill_refs: list[AgentSkillRef] = field(default_factory=list)

    async def run(self, operation):
        try:
            return await asyncio.wait_for(operation(), timeout=self.timeout_seconds)
        except TimeoutError as exc:
            self.stop_reason = "timeout"
            raise MonitoringAgentError("自主监控 Agent 执行超时", status_code=504) from exc

    def reset(self) -> None:
        self.tool_call_count = 0
        self.model_call_count = 0
        self.step_count = 0
        self.stop_reason = ""
        self.skill_refs = []

    def register_skill(self, skill: AgentSkillRef) -> None:
        if all(item.name != skill.name for item in self.skill_refs):
            self.skill_refs.append(skill)
            LOG.info("自主监控Agent skill loaded name={} version={}", skill.name, skill.version)

    async def check_cancelled(self) -> None:
        if self.cancel_check is None:
            return
        result = self.cancel_check()
        cancelled = await result if hasattr(result, "__await__") else result
        if cancelled:
            self.stop_reason = "cancelled"
            raise MonitoringCancelled("自主监控 Agent 已取消", status_code=409)

    async def invoke_model(self, operation):
        await self.check_cancelled()
        if self.model_call_count >= self.max_model_calls or self.step_count >= self.max_steps:
            self.stop_reason = "budget_exceeded"
            raise MonitoringBudgetExceeded("自主监控 Agent 模型调用超过预算", status_code=429)
        self.model_call_count += 1
        self.step_count += 1
        return await operation

    async def invoke_tool(
        self,
        *,
        registry: MonitoringToolRegistry,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        await self.check_cancelled()
        if self.step_count >= self.max_steps or self.tool_call_count >= self.max_tool_calls:
            self.stop_reason = "budget_exceeded"
            raise MonitoringBudgetExceeded("自主监控 Agent 工具调用超过预算", status_code=429)
        authorize_tool(
            name=name,
            arguments=arguments,
            context=context,
            registered_tools=registry.names(),
        )
        self.step_count += 1
        self.tool_call_count += 1
        started_at = utils.utc_now()
        started = perf_counter()
        LOG.info("自主监控Agent tool start name={} call={}", name, self.tool_call_count)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    registry.invoke(name, **arguments),
                    timeout=self.tool_timeout_seconds,
                )
                trace = {
                    "name": name,
                    "status": "completed",
                    "started_at": started_at.isoformat(),
                    "result_count": len(result.get("items") or []),
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                }
                LOG.info(
                    "自主监控Agent tool completed name={} result_count={} duration_ms={}",
                    name,
                    trace["result_count"],
                    trace["duration_ms"],
                )
                return result, trace
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    LOG.warning("自主监控Agent tool retry name={} attempt={}", name, attempt + 1)
        if isinstance(last_error, TimeoutError):
            raise MonitoringAgentError("自主监控 Agent 工具执行超时", status_code=504)
        raise MonitoringAgentError("自主监控 Agent 工具执行失败") from last_error


__all__ = (
    "MonitoringAgentError",
    "MonitoringBudgetExceeded",
    "MonitoringCancelled",
    "MonitoringRuntime",
)
