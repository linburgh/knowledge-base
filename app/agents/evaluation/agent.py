from __future__ import annotations

import asyncio
from time import monotonic

from app.core.common.log import LOG
from app.schemas.evaluation import (
    EvaluationAgentContext,
    EvaluationAgentResult,
    EvaluationAgentTask,
    EvaluationRunSummary,
)

from .config import load_config
from .dataset import load_questions
from .executor import KnowledgeAgentExecutor
from .graph import EvaluationGraph
from .models import EvaluationConfig, EvaluationQuestion
from .runtime import EvaluationCancelled, EvaluationRuntime
from .tools.registry import EvaluationToolRegistry, build_default_registry


class EvaluationAgent:
    """自主评测唯一公开入口。"""

    def __init__(
        self,
        *,
        registry: EvaluationToolRegistry | None = None,
        cancel_check=None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.cancel_check = cancel_check

    async def run(
        self,
        task: EvaluationAgentTask,
        context: EvaluationAgentContext,
    ) -> EvaluationAgentResult:
        agent_task = EvaluationAgentTask.model_validate(task)
        trusted_context = EvaluationAgentContext.model_validate(context)
        config = EvaluationConfig.model_validate(agent_task.config)
        questions = [EvaluationQuestion.model_validate(item) for item in agent_task.questions]

        started = monotonic()
        runtime = EvaluationRuntime(
            config.concurrency,
            config.request_timeout_seconds,
            config.retry_count,
            total_timeout_seconds=config.run_timeout_seconds,
            max_tool_calls=max(len(questions) * (config.retry_count + 1), 1),
            cancel_check=self.cancel_check,
        )
        executor = KnowledgeAgentExecutor(self.registry)
        graph = EvaluationGraph(runtime, executor)
        LOG.info(
            "自主评测Agent start kb_id={} question_count={} concurrency={} retry_count={}",
            config.kb_id,
            len(questions),
            config.concurrency,
            config.retry_count,
        )
        try:
            state = await asyncio.wait_for(
                graph.ainvoke(config, questions, trusted_context),
                timeout=config.run_timeout_seconds,
            )
            LOG.info(
                "自主评测Agent execution finished kb_id={} result_count={}",
                config.kb_id,
                len(state["case_results"]),
            )
            LOG.info(
                "自主评测Agent metrics finished kb_id={} conclusion={} failed_gates={}",
                config.kb_id,
                state["metrics"].conclusion,
                state["metrics"].failed_gates,
            )
            summary = EvaluationRunSummary(
                status=state["status"],
                termination_reason=state["termination_reason"],
                tool_calls=runtime.tool_traces,
                model_call_count=runtime.model_call_count,
                duration_ms=int((monotonic() - started) * 1000),
                limitations=state.get("limitations", []),
                skill_refs=runtime.skill_refs,
                completed_count=state.get("completed_count", 0),
                failed_count=state.get("failed_count", 0),
            )
            result = EvaluationAgentResult(
                case_results=[item.model_dump(mode="json") for item in state["case_results"]],
                metrics=state["metrics"].model_dump(mode="json"),
                report=state["report"],
                conclusion=state["conclusion"],
                summary=summary,
            )
        except EvaluationCancelled:
            partial_results = runtime.partial_results
            result = EvaluationAgentResult(
                case_results=[item.model_dump(mode="json") for item in partial_results],
                metrics={},
                report={},
                conclusion="indeterminate",
                summary=EvaluationRunSummary(
                    status="cancelled",
                    termination_reason="cancelled",
                    tool_calls=runtime.tool_traces,
                    duration_ms=int((monotonic() - started) * 1000),
                    skill_refs=runtime.skill_refs,
                    completed_count=len(partial_results),
                    failed_count=sum(item.status != "completed" for item in partial_results),
                ),
            )
        LOG.info(
            "自主评测Agent completed kb_id={} status={} conclusion={}",
            config.kb_id,
            result.summary.status,
            result.conclusion,
        )
        return result

    @staticmethod
    def load_questions(config: EvaluationConfig) -> list[EvaluationQuestion]:
        if not config.questions_file:
            raise ValueError("generated questions require a generator")
        return load_questions(config.questions_file)


__all__ = ("EvaluationAgent", "load_config")
