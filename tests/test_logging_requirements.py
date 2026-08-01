from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.agents.evaluation.agent import EvaluationAgent
from app.agents.evaluation.models import EvaluationConfig, EvaluationQuestion
from app.agents.evaluation.tools.registry import EvaluationToolRegistry
from app.db.base import LoggingDatabase
from app.schemas.evaluation import (
    EvaluationAgentContext,
    EvaluationAgentTask,
    KnowledgeAgentCallResult,
)


class DatabaseLoggingTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_all_logs_sql_without_parameter_values(self) -> None:
        database = object.__new__(LoggingDatabase)
        with (
            patch("app.db.base.LOG") as log,
            patch(
                "databases.Database.fetch_all",
                new=AsyncMock(return_value=[]),
            ),
        ):
            await database.fetch_all(
                "SELECT * FROM t_user WHERE username = :username",
                {"username": "linburgh"},
            )

        start_message = log.info.call_args_list[0].args
        self.assertIn("SELECT * FROM t_user WHERE username = :username", start_message)
        self.assertIn(["username"], start_message)
        self.assertNotIn("linburgh", str(start_message))


class EvaluationAgentLoggingTest(unittest.IsolatedAsyncioTestCase):
    async def test_agent_logs_lifecycle(self) -> None:
        async def runner(payload, context):
            del payload, context
            from app.schemas.agent import AgentResult

            return KnowledgeAgentCallResult(
                result=AgentResult(
                    answer="答案",
                    mode="single_retrieval",
                    status="completed",
                    top_k=5,
                    hit_count=1,
                    termination_reason="completed",
                    duration_ms=1,
                )
            )

        config = EvaluationConfig(
            kb_id=1,
            user_id=2,
            questions_source="generated",
            business_scope_source="description",
            business_description="测试范围",
        )
        registry = EvaluationToolRegistry()
        registry.register("call_knowledge_agent", runner)
        with patch("app.agents.evaluation.agent.LOG") as agent_log:
            await EvaluationAgent(registry=registry).run(
                EvaluationAgentTask(
                    config=config.model_dump(mode="json"),
                    questions=[EvaluationQuestion(question="测试问题").model_dump(mode="json")],
                ),
                EvaluationAgentContext(
                    run_id=1,
                    task_id=1,
                    user_id="2",
                    kb_id=1,
                    is_super_admin=True,
                ),
            )

        messages = " ".join(str(call.args) for call in agent_log.info.call_args_list)
        self.assertIn("自主评测Agent start", messages)
        self.assertIn("自主评测Agent execution finished", messages)
        self.assertIn("自主评测Agent metrics finished", messages)
        self.assertIn("自主评测Agent completed", messages)


if __name__ == "__main__":
    unittest.main()
