from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from app.agents.policies import authorize_tool
from app.agents.tools.registry import ToolRegistry
from app.core.common.exception import BusiException
from app.schemas.agent import AgentContext, ToolCall, ToolResult


class AgentError(Exception):
    code = "AGENT_ERROR"
    public_message = "Agent 执行失败"
    status_code = 500

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)
        if message:
            self.public_message = message


class ToolPermissionDenied(AgentError):
    code = "TOOL_PERMISSION_DENIED"
    public_message = "工具无权执行"
    status_code = 403


class ToolTimeout(AgentError):
    code = "TOOL_TIMEOUT"
    public_message = "Agent 工具执行超时"
    status_code = 504


class AgentBudgetExceeded(AgentError):
    code = "AGENT_BUDGET_EXCEEDED"
    public_message = "Agent 执行超过预算"
    status_code = 429


class AgentOutputInvalid(AgentError):
    code = "AGENT_OUTPUT_INVALID"
    public_message = "Agent 返回结果不合法"
    status_code = 502


@dataclass(slots=True)
class AgentRuntime:
    registry: ToolRegistry
    max_steps: int
    max_tool_calls: int
    tool_timeout_seconds: float
    max_retries: int = 1
    _call_sequence: Any = field(init=False, repr=False)
    tool_call_count: int = field(init=False, default=0)
    step_count: int = field(init=False, default=0)
    stopped: bool = field(init=False, default=False)
    stop_reason: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self._call_sequence = count(1)
        self.tool_call_count = 0
        self.step_count = 0
        self.stopped = False
        self.stop_reason = ""

    def next_call_id(self) -> str:
        return f"agent-tool-{next(self._call_sequence)}"

    def can_continue(self) -> bool:
        return (
            not self.stopped
            and self.step_count < self.max_steps
            and self.tool_call_count < self.max_tool_calls
        )

    def stop(self, reason: str) -> None:
        self.stopped = True
        self.stop_reason = reason

    def validate_graph_budget(self, tool_call_count: int, model_call_count: int) -> None:
        if tool_call_count > self.max_tool_calls or model_call_count > self.max_steps:
            raise AgentBudgetExceeded("Agent 执行超过预算")

    async def execute(self, call: ToolCall, context: AgentContext) -> ToolResult:
        if not self.can_continue():
            raise AgentBudgetExceeded("Agent 工具调用超过预算")

        try:
            authorize_tool(context=context, call=call, registry=self.registry)
        except BusiException as exc:
            raise ToolPermissionDenied(exc.message) from exc

        handler = self.registry.get(call.name)
        self.tool_call_count += 1
        self.step_count += 1
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await asyncio.wait_for(
                    handler(call, context),
                    timeout=self.tool_timeout_seconds,
                )
            except TimeoutError:
                last_error = ToolTimeout("Agent 工具执行超时")
            except Exception as exc:
                last_error = exc
            if attempt < self.max_retries:
                continue
        if isinstance(last_error, AgentError):
            raise last_error
        raise AgentError("Agent 工具执行失败") from last_error


__all__ = (
    "AgentBudgetExceeded",
    "AgentError",
    "AgentOutputInvalid",
    "AgentRuntime",
    "ToolPermissionDenied",
    "ToolTimeout",
)
