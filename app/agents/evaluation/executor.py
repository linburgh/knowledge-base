from __future__ import annotations

from time import monotonic

from app.core.common.log import LOG
from app.schemas.evaluation import EvaluationAgentContext

from .models import CaseResult, EvaluationQuestion
from .runtime import EvaluationRuntime
from .tools.registry import EvaluationToolRegistry


class KnowledgeAgentExecutor:
    """把知识库 Agent 的公开结果转换为统一的逐题评测结果。

    本类是协议适配器，不负责重试、超时或权限判断；这些职责集中在 Runtime，避免
    未来增加其他执行器时出现不同的安全和失败语义。
    """

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
        # fallback 必须保留为独立状态，不能伪装成 completed；指标层据此判断回答是否
        # 真正经过正常问答链路，后续优化也能区分“低质量答案”和“降级答案”。
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
                "knowledge_agent_skill_refs": [item.model_dump() for item in result.skill_refs],
            },
        )


__all__ = ("KnowledgeAgentExecutor",)
