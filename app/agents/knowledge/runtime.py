"""知识库问答 Agent 的业务预算、取消、重试与工具审计运行时。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from itertools import count
from time import monotonic
from typing import Any

from app.agents.knowledge.policies import authorize_tool
from app.agents.knowledge.tools.registry import ToolRegistry
from app.core.common.exception import BusiException
from app.schemas.agent import AgentContext, AgentSkillRef, AgentToolTrace, ToolCall, ToolResult


class AgentError(Exception):
    """可转换为稳定错误码和安全提示的 Agent 基础异常。"""
    code = "AGENT_ERROR"
    public_message = "Agent 执行失败"
    status_code = 500

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)
        if message:
            self.public_message = message


class ToolPermissionDenied(AgentError):
    """工具未注册、非只读或试图覆盖可信范围。"""
    code = "TOOL_PERMISSION_DENIED"
    public_message = "工具无权执行"
    status_code = 403


class ToolTimeout(AgentError):
    """Agent 总时限或单次模型、工具调用超时。"""
    code = "TOOL_TIMEOUT"
    public_message = "Agent 工具执行超时"
    status_code = 504


class AgentBudgetExceeded(AgentError):
    """模型、工具或步骤次数超过单次任务预算。"""
    code = "AGENT_BUDGET_EXCEEDED"
    public_message = "Agent 执行超过预算"
    status_code = 429


class AgentOutputInvalid(AgentError):
    """模型结果无法通过结构化输出或引用校验。"""
    code = "AGENT_OUTPUT_INVALID"
    public_message = "Agent 返回结果不合法"
    status_code = 502


class AgentCancelled(AgentError):
    """上游取消检查确认当前任务应终止。"""
    code = "AGENT_CANCELLED"
    public_message = "Agent 执行已取消"
    status_code = 409


@dataclass(slots=True)
class AgentRuntime:
    """维护单次问答的可信工具边界、资源预算和调用轨迹。"""
    registry: ToolRegistry
    max_steps: int
    max_tool_calls: int
    tool_timeout_seconds: float
    max_retries: int = 1
    total_timeout_seconds: float = 60.0
    max_model_calls: int = 2
    cancel_check: Callable[[], bool | Awaitable[bool]] | None = None
    _call_sequence: Any = field(init=False, repr=False)
    tool_call_count: int = field(init=False, default=0)
    model_call_count: int = field(init=False, default=0)
    step_count: int = field(init=False, default=0)
    stopped: bool = field(init=False, default=False)
    stop_reason: str = field(init=False, default="")
    tool_traces: list[AgentToolTrace] = field(init=False, default_factory=list)
    skill_refs: list[AgentSkillRef] = field(init=False, default_factory=list)
    _started_at: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._call_sequence = count(1)
        self.tool_call_count = 0
        self.model_call_count = 0
        self.step_count = 0
        self.stopped = False
        self.stop_reason = ""
        self.tool_traces = []
        self.skill_refs = []
        self._started_at = monotonic()

    def remaining_seconds(self) -> float:
        """返回剩余总时限，耗尽时停止运行并抛出超时异常。"""
        remaining = self.total_timeout_seconds - (monotonic() - self._started_at)
        if remaining <= 0:
            self.stop("timeout")
            raise ToolTimeout("Agent 执行超时")
        return remaining

    def next_call_id(self) -> str:
        """生成本次运行内递增的工具调用标识。"""
        return f"agent-tool-{next(self._call_sequence)}"

    def can_continue(self) -> bool:
        """判断是否仍允许发起新的业务工具调用。"""
        return not self.stopped and self.tool_call_count < self.max_tool_calls

    def stop(self, reason: str) -> None:
        """以可审计原因将运行时标记为停止。"""
        self.stopped = True
        self.stop_reason = reason

    def validate_graph_budget(self, tool_call_count: int, model_call_count: int) -> None:
        """校验官方 Harness 实际计数没有越过业务预算。"""
        if tool_call_count > self.max_tool_calls or model_call_count > self.max_model_calls:
            raise AgentBudgetExceeded("Agent 执行超过预算")

    def register_skill(self, skill: AgentSkillRef) -> None:
        """登记本轮加载的 Skill 版本，同名 Skill 只记录一次。"""
        if all(item.name != skill.name for item in self.skill_refs):
            self.skill_refs.append(skill)

    async def check_cancelled(self) -> None:
        """执行可选的同步或异步取消检查。"""
        if self.cancel_check is None:
            return
        value = self.cancel_check()
        cancelled = await value if hasattr(value, "__await__") else value
        if cancelled:
            self.stop("cancelled")
            raise AgentCancelled()

    async def run(self, operation):
        """在 Agent 剩余总时限内执行顶层异步操作。"""
        try:
            return await asyncio.wait_for(operation(), timeout=self.remaining_seconds())
        except TimeoutError as exc:
            self.stop("timeout")
            raise ToolTimeout("Agent 执行超时") from exc

    async def invoke_model(self, operation):
        """检查取消和模型预算后执行一次模型调用。"""
        await self.check_cancelled()
        if self.stopped:
            raise AgentBudgetExceeded("Agent 已停止执行")
        if self.model_call_count >= self.max_model_calls:
            raise AgentBudgetExceeded("Agent 模型调用超过次数预算")
        self.step_count += 1
        self.model_call_count += 1
        try:
            return await asyncio.wait_for(operation, timeout=self.remaining_seconds())
        except TimeoutError as exc:
            raise ToolTimeout("Agent 模型调用超时") from exc

    async def execute(self, call: ToolCall, context: AgentContext) -> ToolResult:
        """授权、限时并重试业务工具调用，同时记录脱敏轨迹。"""
        await self.check_cancelled()
        if not self.can_continue():
            raise AgentBudgetExceeded("Agent 工具调用超过预算")

        try:
            authorize_tool(context=context, call=call, registry=self.registry)
        except BusiException as exc:
            raise ToolPermissionDenied(exc.message) from exc

        handler = self.registry.get(call.name)
        self.tool_call_count += 1
        self.step_count += 1
        started = monotonic()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    handler(call, context),
                    timeout=min(self.tool_timeout_seconds, self.remaining_seconds()),
                )
                self.tool_traces.append(
                    AgentToolTrace(
                        name=call.name,
                        status="completed" if result.ok else "failed",
                        duration_ms=int((monotonic() - started) * 1000),
                        result_count=result.hit_count,
                        error_code=result.error_code,
                    )
                )
                return result
            except TimeoutError:
                last_error = ToolTimeout("Agent 工具执行超时")
            except Exception as exc:
                last_error = exc
            if attempt < self.max_retries:
                continue
        if isinstance(last_error, AgentError):
            self.tool_traces.append(
                AgentToolTrace(
                    name=call.name,
                    status="timeout" if isinstance(last_error, ToolTimeout) else "failed",
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code=last_error.code,
                )
            )
            raise last_error
        self.tool_traces.append(
            AgentToolTrace(
                name=call.name,
                status="failed",
                duration_ms=int((monotonic() - started) * 1000),
                error_code=type(last_error).__name__ if last_error else "UNKNOWN",
            )
        )
        raise AgentError("Agent 工具执行失败") from last_error


__all__ = (
    "AgentBudgetExceeded",
    "AgentCancelled",
    "AgentError",
    "AgentOutputInvalid",
    "AgentRuntime",
    "ToolPermissionDenied",
    "ToolTimeout",
)
