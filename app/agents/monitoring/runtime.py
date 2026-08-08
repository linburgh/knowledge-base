from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from langchain.agents.middleware import AgentMiddleware

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


class MonitoringModelCallAccountingMiddleware(AgentMiddleware):
    """在模型节点执行前记账；即使调用被超时取消也不会丢失计数。"""

    def __init__(self, monitoring_runtime: MonitoringRuntime) -> None:
        self.monitoring_runtime = monitoring_runtime

    async def abefore_model(self, state, runtime) -> None:
        del state, runtime
        self.monitoring_runtime.model_call_count += 1


@dataclass
class MonitoringRuntime:
    timeout_seconds: float = 15.0
    max_context_items: int = 50
    max_steps: int = 8
    max_tool_calls: int = 5
    # Deep Agent 需要为 Skill 发现、工具观察和结构化收敛保留有限轮次。
    max_model_calls: int = 8
    tool_timeout_seconds: float = 5.0
    max_retries: int = 1
    cancel_check: Callable[[], bool | Awaitable[bool]] | None = None
    tool_call_count: int = 0
    model_call_count: int = 0
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

    async def invoke_tool(
        self,
        *,
        registry: MonitoringToolRegistry,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        await self.check_cancelled()
        # 官方 ToolCallLimitMiddleware 还会统计 Skill 读取等内置工具；
        # 这里只限制监控数据查询，属于项目特有的资源预算。
        if self.tool_call_count >= self.max_tool_calls:
            self.stop_reason = "budget_exceeded"
            raise MonitoringBudgetExceeded("自主监控 Agent 查询工具调用超过预算", status_code=429)
        authorize_tool(
            name=name,
            arguments=arguments,
            context=context,
            registered_tools=registry.names(),
        )
        self.tool_call_count += 1
        started_at = utils.utc_now()
        started = perf_counter()
        LOG.info("自主监控Agent tool start name={} call={}", name, self.tool_call_count)
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

    @staticmethod
    def failed_trace(name: str, error: Exception) -> dict[str, Any]:
        """ToolRetryMiddleware 负责重试，Runtime 只记录本次失败。"""
        return {
            "name": name,
            "status": "failed",
            "started_at": utils.utc_now().isoformat(),
            "error": type(error).__name__,
        }


__all__ = (
    "MonitoringAgentError",
    "MonitoringBudgetExceeded",
    "MonitoringCancelled",
    "MonitoringModelCallAccountingMiddleware",
    "MonitoringRuntime",
)
