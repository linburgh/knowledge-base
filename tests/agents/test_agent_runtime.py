from __future__ import annotations

import unittest

from app.agents.knowledge.runtime import AgentBudgetExceeded, AgentRuntime
from app.agents.knowledge.tools.registry import ToolRegistry
from app.schemas.agent import AgentContext, ToolCall, ToolResult


class AgentRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_budget_stops_tool_calls(self) -> None:
        registry = ToolRegistry()

        async def handler(call: ToolCall, context: AgentContext) -> ToolResult:
            del context
            return ToolResult(call_id=call.call_id, name=call.name, ok=True)

        registry.register("retrieve_knowledge", handler)
        runtime = AgentRuntime(
            registry=registry,
            max_steps=1,
            max_tool_calls=1,
            tool_timeout_seconds=1,
        )
        context = AgentContext(user_id="u1", kb_id=1)
        call = ToolCall(call_id="c1", name="retrieve_knowledge", input={})
        await runtime.execute(call, context)
        with self.assertRaises(AgentBudgetExceeded):
            await runtime.execute(call, context)
