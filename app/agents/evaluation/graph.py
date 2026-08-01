from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.core.common.log import LOG
from app.schemas.evaluation import EvaluationAgentContext

from .executor import KnowledgeAgentExecutor
from .metrics import calculate_metrics
from .models import EvaluationConfig, EvaluationQuestion
from .policies import validate_config, validate_evaluation_context
from .report import build_report
from .runtime import EvaluationRuntime
from .skills import load_evaluation_skill
from .state import EvaluationState


class EvaluationGraph:
    """自主评测生产状态图。"""

    def __init__(self, runtime: EvaluationRuntime, executor: KnowledgeAgentExecutor) -> None:
        self.runtime = runtime
        self.executor = executor
        self.compiled = self._build().compile()

    def _build(self) -> StateGraph:
        graph = StateGraph(EvaluationState)

        async def validate_config_node(state: EvaluationState):
            config: EvaluationConfig = state["config"]
            context: EvaluationAgentContext = state["context"]
            validate_config(config)
            validate_evaluation_context(config, context)
            LOG.info("自主评测Agent graph node completed node=validate_config")
            return {"current_node": "validate_config", "status": "running"}

        async def load_skill_node(state: EvaluationState):
            del state
            _, skill_ref = load_evaluation_skill()
            self.runtime.register_skill(skill_ref)
            LOG.info("自主评测Agent graph node completed node=load_skill")
            return {"current_node": "load_skill"}

        async def prepare_questions_node(state: EvaluationState):
            questions = state["questions"]
            if not questions:
                raise ValueError("评测问题集为空")
            LOG.info(
                "自主评测Agent graph node completed node=prepare_questions count={}",
                len(questions),
            )
            return {"current_node": "prepare_questions", "prepared_questions": questions}

        async def dispatch_cases_node(state: EvaluationState):
            await self.runtime.check_cancelled()
            LOG.info(
                "自主评测Agent graph node completed node=dispatch_cases count={}",
                len(state["prepared_questions"]),
            )
            return {"current_node": "dispatch_cases"}

        async def execute_case_node(state: EvaluationState):
            config: EvaluationConfig = state["config"]
            context: EvaluationAgentContext = state["context"]
            results = await self.runtime.run(
                state["prepared_questions"],
                lambda case_no, question: self.executor.execute(
                    case_no,
                    question,
                    config=config,
                    context=context,
                    runtime=self.runtime,
                ),
                monitoring_fields=context.monitoring_fields,
            )
            failed_count = sum(item.status != "completed" for item in results)
            LOG.info("自主评测Agent graph node completed node=execute_case count={}", len(results))
            return {
                "current_node": "execute_case",
                "case_results": results,
                "completed_count": len(results),
                "failed_count": failed_count,
            }

        async def calculate_metrics_node(state: EvaluationState):
            metrics = calculate_metrics(state["case_results"], state["config"].gates)
            LOG.info("自主评测Agent graph node completed node=calculate_metrics")
            return {
                "current_node": "calculate_metrics",
                "metrics": metrics,
                "conclusion": metrics.conclusion,
            }

        async def build_report_node(state: EvaluationState):
            report = build_report(state["config"], state["case_results"], state["metrics"])
            LOG.info("自主评测Agent graph node completed node=build_report")
            return {"current_node": "build_report", "report": report}

        async def finalize_node(state: EvaluationState):
            del state
            LOG.info("自主评测Agent graph node completed node=finalize")
            return {
                "current_node": "finalize",
                "status": "completed",
                "termination_reason": "completed",
            }

        graph.add_node("validate_config", validate_config_node)
        graph.add_node("load_skill", load_skill_node)
        graph.add_node("prepare_questions", prepare_questions_node)
        graph.add_node("dispatch_cases", dispatch_cases_node)
        graph.add_node("execute_case", execute_case_node)
        graph.add_node("calculate_metrics", calculate_metrics_node)
        graph.add_node("build_report", build_report_node)
        graph.add_node("finalize", finalize_node)
        graph.add_edge(START, "validate_config")
        graph.add_edge("validate_config", "load_skill")
        graph.add_edge("load_skill", "prepare_questions")
        graph.add_edge("prepare_questions", "dispatch_cases")
        graph.add_edge("dispatch_cases", "execute_case")
        graph.add_edge("execute_case", "calculate_metrics")
        graph.add_edge("calculate_metrics", "build_report")
        graph.add_edge("build_report", "finalize")
        graph.add_edge("finalize", END)
        return graph

    async def ainvoke(
        self,
        config: EvaluationConfig,
        questions: list[EvaluationQuestion],
        context: EvaluationAgentContext,
    ) -> EvaluationState:
        LOG.info(
            "自主评测Agent graph start kb_id={} question_count={}",
            config.kb_id,
            len(questions),
        )
        return await self.compiled.ainvoke(
            {"config": config, "questions": questions, "context": context}
        )


__all__ = ("EvaluationGraph",)
