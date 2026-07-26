from __future__ import annotations

from .config import load_config
from .dataset import load_questions
from .executor import KnowledgeAgentExecutor
from .metrics import calculate_metrics
from .models import CaseResult, EvaluationConfig, EvaluationMetrics, EvaluationQuestion
from .policies import validate_config
from .runtime import EvaluationRuntime


class EvaluationAgent:
    """评测专属编排入口；问答事实只能来自注入的公开 knowledge Agent 协议。"""

    def __init__(self, knowledge_runner) -> None:
        self.executor = KnowledgeAgentExecutor(knowledge_runner)

    async def run(
        self, config: EvaluationConfig, questions: list[EvaluationQuestion]
    ) -> tuple[list[CaseResult], EvaluationMetrics]:
        validate_config(config)
        results = await EvaluationRuntime(
            config.concurrency, config.request_timeout_seconds, config.retry_count
        ).run(
            questions,
            lambda case_no, question: self.executor.execute(case_no, question, config=config),
        )
        return results, calculate_metrics(results, config.gates)

    @staticmethod
    def load_questions(config: EvaluationConfig) -> list[EvaluationQuestion]:
        validate_config(config)
        if not config.questions_file:
            raise ValueError("generated questions require a generator")
        return load_questions(config.questions_file)


__all__ = ("EvaluationAgent", "load_config")
