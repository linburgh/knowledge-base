from __future__ import annotations

import unittest

from app.agents.knowledge.policies import authorize_tool
from app.agents.knowledge.tools.registry import build_default_registry
from app.core.common.exception import BusiException
from app.schemas.agent import AgentContext, ToolCall


class AgentPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = AgentContext(user_id="u1", kb_id=3)
        self.registry = build_default_registry()

    def test_unregistered_tool_is_rejected(self) -> None:
        with self.assertRaises(BusiException):
            authorize_tool(
                context=self.context,
                call=ToolCall(call_id="c1", name="retrieve_knowledge", input={"kb_id": 4}),
                registry=self.registry,
            )

    def test_context_fields_cannot_be_overridden(self) -> None:
        with self.assertRaises(BusiException):
            authorize_tool(
                context=self.context,
                call=ToolCall(
                    call_id="c1",
                    name="retrieve_knowledge",
                    input={"tenant_id": 10, "query": "test"},
                ),
                registry=self.registry,
            )

    def test_only_read_tools_are_registered(self) -> None:
        self.assertEqual(
            self.registry.names(),
            {"retrieve_knowledge", "load_conversation_history", "build_citations"},
        )
