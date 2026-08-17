from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.agents.evaluation.metrics import calculate_metrics
from app.agents.evaluation.models import CaseResult, EvaluationQuestion
from app.core.services.platform import evaluation as evaluation_service
from app.db.base import DB
from app.schemas.evaluation import EvaluationAgentResult, EvaluationRunSummary
from app.workers import evaluation as evaluation_worker


class FakeDB:
    @asynccontextmanager
    async def transaction(self):
        yield self


class EvaluationCoreFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_new_task_can_create_run_and_worker_persists_output(self) -> None:
        db = FakeDB()
        DB.set(db)
        current_user = SimpleNamespace(user_id="204")
        task = {
            "id": 7,
            "status": "active",
            "config": {
                "kb_id": 28,
                "user_id": 204,
                "questions_source": "imported",
                "questions_file": "smoke.jsonl",
                "questions_content": '{"question":"仓储管理系统有哪些功能？"}\n',
                "business_scope_source": "description",
                "gates": {},
            },
        }
        run = {
            "id": 11,
            "task_id": 7,
            "run_no": 1,
            "status": "pending",
            "stage": "prepare",
            "completed_count": 0,
            "failed_count": 0,
        }
        updates: list[dict] = []
        inserted_cases: list[dict] = []

        async def run_update(db, values, **kwargs):
            updates.append(values)

        async def agent_run(agent_task, agent_context):
            del agent_context
            question = agent_task.questions[0]["question"]
            result = CaseResult(
                case_no=1,
                question=question,
                question_source="imported",
                answer="仓储管理系统支持入库、出库和库存管理。",
                status="completed",
            )
            metrics = calculate_metrics([result], {})
            return EvaluationAgentResult(
                case_results=[result.model_dump(mode="json")],
                metrics=metrics.model_dump(mode="json"),
                report={"conclusion": metrics.conclusion},
                conclusion=metrics.conclusion,
                summary=EvaluationRunSummary(
                    status="completed",
                    termination_reason="completed",
                    completed_count=1,
                ),
            )

        async def case_insert(db, **values):
            inserted_cases.append(values)
            return 1

        async def run_get(db, **kwargs):
            if kwargs.get("id") == 11:
                return run
            return None

        with (
            patch.object(evaluation_service, "require_evaluation_access", new=AsyncMock()),
            patch.object(evaluation_service, "tenant_scope", new=AsyncMock(return_value=None)),
            patch.object(evaluation_service.task_db, "get", new=AsyncMock(return_value=task)),
            patch.object(evaluation_service.run_db, "list", new=AsyncMock(return_value=[])),
            patch.object(evaluation_service.run_db, "insert_", new=AsyncMock(return_value=11)),
            patch.object(evaluation_service.run_db, "get", new=AsyncMock(return_value=run)),
            patch.object(evaluation_service.audit_service, "record", new=AsyncMock()),
        ):
            created_run = await evaluation_service.create_run.__wrapped__.__wrapped__(
                7, current_user
            )

        self.assertEqual(created_run["status"], "pending")
        self.assertEqual(created_run["task_id"], 7)

        with (
            patch.object(evaluation_worker.run_db, "get", new=AsyncMock(side_effect=run_get)),
            patch.object(evaluation_worker.task_db, "get", new=AsyncMock(return_value=task)),
            patch.object(
                evaluation_worker,
                "load_questions_content",
                new=Mock(
                    return_value=[EvaluationQuestion(question="仓储管理系统有哪些功能？")]
                ),
            ),
            patch.object(evaluation_worker.case_db, "insert_", new=case_insert),
            patch.object(evaluation_worker.run_db, "update_", new=run_update),
            patch.object(
                evaluation_worker.knowledge_base_db,
                "get",
                new=AsyncMock(
                    return_value={
                        "id": 28,
                        "status": "active",
                        "system_prompt": "",
                        "active_index_version_id": 1,
                    }
                ),
            ),
            patch.object(
                evaluation_worker.qa_config_service,
                "get_effective_config",
                new=AsyncMock(return_value={}),
            ),
            patch.object(evaluation_worker, "EvaluationAgent") as agent_class,
        ):
            agent_class.return_value.run = agent_run
            await evaluation_worker.run_evaluation.__wrapped__.__wrapped__(11)

        self.assertEqual(len(inserted_cases), 1)
        self.assertEqual(inserted_cases[0]["question"], "仓储管理系统有哪些功能？")
        self.assertEqual(updates[0]["status"], "running")
        self.assertEqual(updates[0]["stage"], "prepare")
        self.assertEqual(updates[1]["stage"], "execute")
        self.assertEqual(updates[2]["stage"], "metrics")
        self.assertEqual(updates[-1]["status"], "completed")
        self.assertEqual(updates[-1]["stage"], "report")
        self.assertEqual(updates[-1]["question_count"], 1)
        self.assertEqual(updates[-1]["completed_count"], 1)
        self.assertEqual(updates[-1]["failed_count"], 0)

    async def test_task_without_run_is_not_reported_as_running(self) -> None:
        db = FakeDB()
        DB.set(db)
        with (
            patch.object(evaluation_service, "require_evaluation_access", new=AsyncMock()),
            patch.object(evaluation_service, "tenant_scope", new=AsyncMock(return_value=None)),
            patch.object(
                evaluation_service.task_db,
                "list",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": 8,
                            "name": "未执行任务",
                            "created_by": "204",
                        }
                    ]
                ),
            ),
            patch.object(evaluation_service.run_db, "list", new=AsyncMock(return_value=[])),
            patch.object(
                evaluation_service.user_db,
                "get",
                new=AsyncMock(return_value={"display_name": "管理员", "username": "admin"}),
            ),
        ):
            result = await evaluation_service.page.__wrapped__.__wrapped__(
                SimpleNamespace(user_id="204")
            )

        self.assertEqual(result["items"][0]["latest_run_status"], "not_started")


if __name__ == "__main__":
    unittest.main()
