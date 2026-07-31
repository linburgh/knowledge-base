from __future__ import annotations

from app.core.common.log import LOG

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
        self,
        config: EvaluationConfig,
        questions: list[EvaluationQuestion],
        *,
        monitoring_fields: dict | None = None,
    ) -> tuple[list[CaseResult], EvaluationMetrics]:
        LOG.info(
            "自主评测Agent start kb_id={} question_count={} concurrency={} retry_count={}",
            config.kb_id,
            len(questions),
            config.concurrency,
            config.retry_count,
        )
        validate_config(config)
        LOG.info(
            "自主评测Agent config validated kb_id={} questions_source={} scope_source={}",
            config.kb_id,
            config.questions_source,
            config.business_scope_source,
        )
        results = await EvaluationRuntime(
            config.concurrency, config.request_timeout_seconds, config.retry_count
        ).run(
            questions,
            lambda case_no, question: self.executor.execute(case_no, question, config=config),
            monitoring_fields=monitoring_fields,
        )
        LOG.info(
            "自主评测Agent execution finished kb_id={} result_count={}",
            config.kb_id,
            len(results),
        )
        metrics = calculate_metrics(results, config.gates)
        LOG.info(
            "自主评测Agent metrics finished kb_id={} conclusion={} failed_gates={}",
            config.kb_id,
            metrics.conclusion,
            metrics.failed_gates,
        )
        LOG.info(
            "自主评测Agent completed kb_id={} conclusion={} result_count={}",
            config.kb_id,
            metrics.conclusion,
            len(results),
        )
        return results, metrics

    @staticmethod
    def load_questions(config: EvaluationConfig) -> list[EvaluationQuestion]:
        validate_config(config)
        if not config.questions_file:
            raise ValueError("generated questions require a generator")
        return load_questions(config.questions_file)


__all__ = ("EvaluationAgent", "load_config")
