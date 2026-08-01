from __future__ import annotations

from time import monotonic

from app.core.common.log import LOG
from app.schemas.evaluation import EvaluationAgentContext

from .models import CaseResult, EvaluationQuestion
from .runtime import EvaluationRuntime
from .tools.registry import EvaluationToolRegistry


class KnowledgeAgentExecutor:
    """逐题执行器；生产路径只通过评测 Registry 调用知识 Agent。"""

    def __init__(self, registry: EvaluationToolRegistry) -> None:
        self.registry = registry

    async def execute(
        self,
        case_no: int,
        question: EvaluationQuestion,
        *,
        config,
        context: EvaluationAgentContext | None = None,
        runtime: EvaluationRuntime | None = None,
    ) -> CaseResult:
        started = monotonic()
        LOG.info(
            "自主评测Agent knowledge agent start case_no={} kb_id={} question_length={}",
            case_no,
            config.kb_id,
            len(question.question),
        )
        if context is None or runtime is None:
            raise RuntimeError("评测 Registry 执行缺少可信上下文或 Runtime")
        call_result = await runtime.invoke_tool(
            registry=self.registry,
            name="call_knowledge_agent",
            payload={"case_no": case_no, "question": question.question},
            context=context,
        )
        result = call_result.result
        status = "fallback" if result.termination_reason == "fallback" else "completed"
        LOG.info(
            "自主评测Agent knowledge agent finished "
            "case_no={} status={} citations={} hit_count={} duration_ms={}",
            case_no,
            status,
            len(result.citations),
            result.hit_count,
            max(result.duration_ms, int((monotonic() - started) * 1000)),
        )
        return CaseResult(
            case_no=case_no,
            question=question.question,
            question_source=question.source,
            question_basis=question.question_basis,
            answer=result.answer,
            status=status,
            termination_reason=result.termination_reason,
            citation_count=len(result.citations),
            hit_count=result.hit_count,
            duration_ms=max(result.duration_ms, int((monotonic() - started) * 1000)),
            metadata={
                "citations": [citation.model_dump(mode="json") for citation in result.citations],
                "knowledge_agent_skill_refs": [
                    item.model_dump() for item in result.skill_refs
                ],
            },
        )


__all__ = ("KnowledgeAgentExecutor",)
