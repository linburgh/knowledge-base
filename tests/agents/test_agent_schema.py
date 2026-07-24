from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.schemas.agent import AgentResult, AgentTask, ToolCall


class AgentSchemaTest(unittest.TestCase):
    def test_task_rejects_blank_question(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(kb_id=1, question=" ", user_id="u1")

    def test_task_rejects_invalid_top_k(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(kb_id=1, question="问题", user_id="u1", top_k=51)

    def test_tool_name_is_closed(self) -> None:
        with self.assertRaises(ValidationError):
            ToolCall(call_id="c1", name="execute", input={})

    def test_result_requires_answer(self) -> None:
        with self.assertRaises(ValidationError):
            AgentResult(
                answer="",
                mode="single_retrieval",
                status="completed",
                top_k=5,
                hit_count=0,
                termination_reason="completed",
                duration_ms=1,
            )
