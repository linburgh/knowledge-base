from __future__ import annotations

import asyncio
import unittest

from app.agents.evaluation.executor import KnowledgeAgentExecutor
from app.agents.evaluation.generator import generate_questions
from app.agents.evaluation.metrics import calculate_metrics
from app.agents.evaluation.models import (
    CaseResult,
    EvaluationConfig,
    EvaluationQuestion,
    Gate,
)
from app.agents.evaluation.runtime import EvaluationRuntime
from app.schemas.agent import AgentResult
from workers.evaluation import _load_generation_context


def config(**kwargs) -> EvaluationConfig:
    values = {
        "kb_id": 1,
        "user_id": 2,
        "questions_source": "generated",
        "business_scope_source": "description",
        "business_description": "报销流程",
    }
    values.update(kwargs)
    return EvaluationConfig(**values)


class EvaluationAgentTest(unittest.IsolatedAsyncioTestCase):
    async def test_generate_modes(self) -> None:
        description = await generate_questions(config(), None)
        self.assertEqual(description[0].source, "generated")
        self.assertEqual(description[0].question_basis, "description")

        knowledge = await generate_questions(
            config(business_scope_source="knowledge_base", business_description=None),
            "报销制度",
        )
        self.assertEqual(knowledge[0].question_basis, "knowledge_base")

        combined = await generate_questions(
            config(business_scope_source="description_and_knowledge_base"),
            "报销制度",
        )
        self.assertEqual(combined[0].question_basis, "both")

    async def test_runtime_limits_concurrency_and_keeps_all_results(self) -> None:
        active = 0
        maximum = 0

        async def execute(case_no: int, question: EvaluationQuestion) -> CaseResult:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return CaseResult(
                case_no=case_no,
                question=question.question,
                question_source=question.source,
                status="completed",
            )

        questions = [EvaluationQuestion(question=f"问题 {index}") for index in range(5)]
        results = await EvaluationRuntime(2, 1).run(questions, execute)
        self.assertEqual(len(results), 5)
        self.assertLessEqual(maximum, 2)
        self.assertTrue(all(item.status == "completed" for item in results))

    async def test_runtime_records_timeout_and_error(self) -> None:
        async def execute(case_no: int, question: EvaluationQuestion) -> CaseResult:
            if case_no == 1:
                await asyncio.sleep(0.05)
            if case_no == 2:
                raise RuntimeError("model unavailable")
            return CaseResult(
                case_no=case_no,
                question=question.question,
                question_source=question.source,
                status="completed",
            )

        results = await EvaluationRuntime(3, 0.01).run(
            [EvaluationQuestion(question=f"问题 {index}") for index in range(1, 4)],
            execute,
        )
        self.assertEqual(results[0].status, "timeout")
        self.assertEqual(results[0].error_code, "REQUEST_TIMEOUT")
        self.assertEqual(results[1].status, "error")
        self.assertEqual(results[1].error_code, "CASE_EXECUTION_ERROR")
        self.assertEqual(results[2].status, "completed")

    async def test_runtime_retries_a_transient_failure(self) -> None:
        attempts = 0

        async def execute(case_no: int, question: EvaluationQuestion) -> CaseResult:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary model failure")
            return CaseResult(
                case_no=case_no,
                question=question.question,
                question_source=question.source,
                status="completed",
            )

        results = await EvaluationRuntime(1, 1, retry_count=1).run(
            [EvaluationQuestion(question="可重试问题")], execute
        )
        self.assertEqual(attempts, 2)
        self.assertEqual(results[0].status, "completed")

    async def test_executor_maps_fallback_result(self) -> None:
        async def runner(task, context):
            return AgentResult(
                answer="资料不足",
                mode="single_retrieval",
                status="completed",
                top_k=5,
                hit_count=0,
                termination_reason="fallback",
                duration_ms=3,
            )

        result = await KnowledgeAgentExecutor(runner).execute(
            1,
            EvaluationQuestion(question="问题"),
            config=config(),
        )
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.termination_reason, "fallback")

    def test_metrics_keep_fallback_and_gate_conclusion(self) -> None:
        results = [
            CaseResult(case_no=1, question="1", question_source="imported", status="completed"),
            CaseResult(case_no=2, question="2", question_source="imported", status="fallback"),
        ]
        metrics = calculate_metrics(
            results,
            {"success_rate": Gate(operator=">=", value=0.5)},
        )
        self.assertEqual(metrics.metrics["fallback_rate"].value, 0.5)
        self.assertEqual(metrics.conclusion, "passed")

    def test_generated_knowledge_mode_requires_knowledge_context(self) -> None:
        import asyncio

        with self.assertRaisesRegex(ValueError, "knowledge text is required"):
            asyncio.run(
                generate_questions(
                    config(
                        business_scope_source="knowledge_base",
                        business_description=None,
                    ),
                    None,
                )
            )

    async def test_worker_loads_knowledge_chunks_for_generation(self) -> None:
        class ChunkDB:
            async def list(self, db, **kwargs):
                self.kwargs = kwargs
                return [{"content": " 报销需要发票。 "}, {"content": ""}]

        import workers.evaluation as worker

        original = worker.document_chunk_db.list
        worker.document_chunk_db.list = ChunkDB().list
        try:
            context = await _load_generation_context(
                object(),
                config(
                    business_scope_source="knowledge_base",
                    business_description=None,
                ),
                None,
            )
        finally:
            worker.document_chunk_db.list = original
        self.assertEqual(context, "报销需要发票。")


if __name__ == "__main__":
    unittest.main()
