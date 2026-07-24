from __future__ import annotations

from pydantic import StrictBool, StrictFloat, StrictInt

from app.config.base import Opt

enabled = Opt(
    name="enabled",
    description="Enable the knowledge agent",
    schema=StrictBool,
    default=True,
)
max_steps = Opt(
    name="max_steps",
    description="Maximum agent graph recursion steps",
    schema=StrictInt,
    default=4,
)
max_tool_calls = Opt(
    name="max_tool_calls",
    description="Maximum read-only tool calls per request",
    schema=StrictInt,
    default=6,
)
tool_timeout_seconds = Opt(
    name="tool_timeout_seconds",
    description="Timeout for one tool call",
    schema=StrictFloat,
    default=10.0,
)
total_timeout_seconds = Opt(
    name="total_timeout_seconds",
    description="Timeout for one agent request",
    schema=StrictFloat,
    default=60.0,
)
max_context_chars = Opt(
    name="max_context_chars",
    description="Maximum context characters",
    schema=StrictInt,
    default=24000,
)
max_history_messages = Opt(
    name="max_history_messages",
    description="Maximum conversation history messages",
    schema=StrictInt,
    default=10,
)
max_retries = Opt(
    name="max_retries",
    description="Maximum retry count for read-only tools",
    schema=StrictInt,
    default=1,
)

GROUP_NAME = __name__.split(".")[-1]
ALL_OPTS = (
    enabled,
    max_steps,
    max_tool_calls,
    tool_timeout_seconds,
    total_timeout_seconds,
    max_context_chars,
    max_history_messages,
    max_retries,
)

__all__ = ("GROUP_NAME", "ALL_OPTS")
