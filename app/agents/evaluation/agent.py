from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import lru_cache
from time import monotonic
from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain.agents.structured_output import ToolStrategy

from app.core.common.exception import BusiException
from app.core.common.log import LOG
from app.schemas.agent import AgentToolTrace
from app.schemas.evaluation import (
    EvaluationAgentContext,
    EvaluationAgentResult,
    EvaluationAgentTask,
    EvaluationRunSummary,
)

from .config import load_config
from .dataset import load_questions
from .executor import KnowledgeAgentExecutor
from .model import build_evaluation_chat_model
from .models import EvaluationAgentOutput, EvaluationConfig, EvaluationQuestion
from .policies import validate_config, validate_evaluation_context
from .report import build_report
from .runtime import EvaluationCancelled, EvaluationRuntime
from .skills import load_evaluation_skill
from .state import EvaluationHarnessContext, EvaluationSession
from .tools import (
    execute_evaluation_cases,
    inspect_evaluation_results,
    retry_evaluation_cases,
)
from .tools.registry import EvaluationToolRegistry, build_default_registry

EVALUATION_SYSTEM_PROMPT = """你是企业知识库问答的自主评测 Agent。
开始工作后先读取 /skills/analysis/SKILL.md，并按照技能要求执行。
首次必须调用无参数的 execute_evaluation_cases，由工具执行任务中的全部问题，不能抽样。
然后调用 inspect_evaluation_results 观察确定性指标、失败、超时、降级和引用异常。
证据不足且仍有复核预算时，可以自主选择部分题号调用 retry_evaluation_cases。
复核只用于区分瞬时故障与稳定缺陷，不得反复执行正常题目，也不得超过工具返回的预算。
业务问题答案只能来自评测执行工具内部调用的知识库 Agent；你不得自行回答测试问题。
最终返回结构化评测分析，包括目标、理由、发现、建议、置信度和终止原因。
发现和建议必须引用工具返回的题号、状态或指标，不得虚构知识库内容、配置或执行结果。
最终是否通过由系统的确定性门禁计算，你不得修改或代替门禁结论。
"""

EXCLUDED_BUILTIN_TOOLS = frozenset(
    {
        "write_todos",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
        "execute",
        "task",
    }
)


@lru_cache(maxsize=1)
def _register_evaluation_harness_profile() -> None:
    """注册只读 Harness；重复注册时 Deep Agents 按集合合并，结果保持幂等。"""
    register_harness_profile(
        "openai",
        HarnessProfile(
            excluded_tools=EXCLUDED_BUILTIN_TOOLS,
            excluded_middleware=frozenset({"TodoListMiddleware"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def _build_filesystem_permissions() -> list[FilesystemPermission]:
    return [
        FilesystemPermission(operations=["read"], paths=["/skills/**"], mode="allow"),
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/**"],
            mode="deny",
        ),
    ]


def build_evaluation_deep_agent(
    config: EvaluationConfig,
    *,
    model: Any | None = None,
):
    """使用官方 Deep Agents API 创建自主评测生产 Harness。"""
    _register_evaluation_harness_profile()
    middleware: list[Any] = [
        ToolCallLimitMiddleware(
            run_limit=(config.max_review_rounds + 1) * 2 + 4,
            exit_behavior="error",
        ),
        ModelCallLimitMiddleware(
            run_limit=config.max_model_calls,
            exit_behavior="error",
        ),
    ]
    if config.retry_count > 0:
        middleware.extend(
            [
                ModelRetryMiddleware(max_retries=config.retry_count),
                ToolRetryMiddleware(
                    max_retries=config.retry_count,
                    tools=[
                        "execute_evaluation_cases",
                        "retry_evaluation_cases",
                        "inspect_evaluation_results",
                    ],
                    retry_on=(TimeoutError,),
                ),
            ]
        )
    return create_deep_agent(
        model=model or build_evaluation_chat_model(),
        tools=[
            execute_evaluation_cases,
            retry_evaluation_cases,
            inspect_evaluation_results,
        ],
        system_prompt=EVALUATION_SYSTEM_PROMPT,
        skills=["/skills/"],
        backend=StateBackend(),
        permissions=_build_filesystem_permissions(),
        response_format=ToolStrategy(EvaluationAgentOutput),
        context_schema=EvaluationHarnessContext,
        middleware=middleware,
        subagents=[],
        name="evaluation_agent",
        debug=False,
    )


def _skill_files(content: str) -> dict[str, dict[str, str]]:
    return {"/skills/analysis/SKILL.md": {"content": content}}


def _agent_tool_traces(result: dict[str, Any]) -> list[AgentToolTrace]:
    traces: list[AgentToolTrace] = []
    for message in result.get("messages", []):
        if getattr(message, "type", None) != "tool":
            continue
        status = getattr(message, "status", "success")
        traces.append(
            AgentToolTrace(
                name=getattr(message, "name", None) or "unknown_tool",
                status="failed" if status == "error" else "completed",
                error_code="TOOL_ERROR" if status == "error" else None,
            )
        )
    return traces


def _model_call_count(result: dict[str, Any]) -> int:
    return sum(getattr(message, "type", None) == "ai" for message in result.get("messages", []))


class EvaluationAgent:
    """自主评测 Deep Agent Harness 的唯一公开入口。"""

    def __init__(
        self,
        *,
        registry: EvaluationToolRegistry | None = None,
        cancel_check=None,
        agent_factory: Callable[[EvaluationConfig], Any] | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.cancel_check = cancel_check
        self.agent_factory = agent_factory

    async def run(
        self,
        task: EvaluationAgentTask,
        context: EvaluationAgentContext,
    ) -> EvaluationAgentResult:
        agent_task = EvaluationAgentTask.model_validate(task)
        trusted_context = EvaluationAgentContext.model_validate(context)
        config = EvaluationConfig.model_validate(agent_task.config)
        questions = [EvaluationQuestion.model_validate(item) for item in agent_task.questions]
        validate_config(config)
        validate_evaluation_context(config, trusted_context)

        started = monotonic()
        runtime = EvaluationRuntime(
            config.concurrency,
            config.request_timeout_seconds,
            config.retry_count,
            total_timeout_seconds=config.run_timeout_seconds,
            max_tool_calls=max(
                len(questions) * (config.retry_count + 1) * (config.max_review_rounds + 1),
                1,
            ),
            cancel_check=self.cancel_check,
        )
        skill_content, skill_ref = load_evaluation_skill()
        runtime.register_skill(skill_ref)
        session = EvaluationSession(
            config=config,
            questions=questions,
            trusted_context=trusted_context,
            executor=KnowledgeAgentExecutor(self.registry),
            runtime=runtime,
        )
        agent = (
            self.agent_factory(config)
            if self.agent_factory is not None
            else build_evaluation_deep_agent(config)
        )
        LOG.info(
            "自主评测Agent start run_id={} kb_id={} question_count={} harness=deepagents",
            trusted_context.run_id,
            config.kb_id,
            len(questions),
        )
        try:
            result_state = await asyncio.wait_for(
                agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    f"执行自主评测。题号范围：1-{len(questions)}。"
                                    f"业务范围来源：{config.business_scope_source}。"
                                    f"门禁配置：{config.model_dump(mode='json')['gates']}。"
                                ),
                            }
                        ],
                        "files": _skill_files(skill_content),
                    },
                    context=EvaluationHarnessContext(session=session),
                    config={"recursion_limit": max(config.max_model_calls * 16 + 16, 64)},
                ),
                timeout=config.run_timeout_seconds,
            )
            if not session.all_cases_completed():
                raise BusiException("自主评测 Agent 未完成全部初次问题")
            raw_output = result_state.get("structured_response")
            if raw_output is None:
                raise BusiException("自主评测 Agent 未返回结构化结果")
            analysis = (
                raw_output
                if isinstance(raw_output, EvaluationAgentOutput)
                else EvaluationAgentOutput.model_validate(raw_output)
            )
            analysis = analysis.model_copy(
                update={"reviewed_case_numbers": session.reviewed_case_numbers}
            )
            results = session.ordered_results()
            metrics = session.metrics()
            LOG.info(
                "自主评测Agent execution finished run_id={} result_count={} review_round={}",
                trusted_context.run_id,
                len(results),
                session.review_round,
            )
            LOG.info(
                "自主评测Agent metrics finished run_id={} conclusion={} failed_gates={}",
                trusted_context.run_id,
                metrics.conclusion,
                metrics.failed_gates,
            )
            report = build_report(config, results, metrics, analysis=analysis)
            runtime.model_call_count = _model_call_count(result_state)
            traces = [*_agent_tool_traces(result_state), *runtime.tool_traces]
            result = EvaluationAgentResult(
                case_results=[item.model_dump(mode="json") for item in results],
                metrics=metrics.model_dump(mode="json"),
                report=report,
                conclusion=metrics.conclusion,
                summary=EvaluationRunSummary(
                    status="completed",
                    termination_reason=analysis.termination_reason,
                    tool_calls=traces,
                    model_call_count=runtime.model_call_count,
                    duration_ms=int((monotonic() - started) * 1000),
                    skill_refs=runtime.skill_refs,
                    completed_count=len(results),
                    failed_count=sum(item.status != "completed" for item in results),
                ),
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
                    model_call_count=runtime.model_call_count,
                    duration_ms=int((monotonic() - started) * 1000),
                    skill_refs=runtime.skill_refs,
                    completed_count=len(partial_results),
                    failed_count=sum(item.status != "completed" for item in partial_results),
                ),
            )
        LOG.info(
            "自主评测Agent completed run_id={} status={} conclusion={} "
            "model_calls={} tool_calls={}",
            trusted_context.run_id,
            result.summary.status,
            result.conclusion,
            result.summary.model_call_count,
            len(result.summary.tool_calls),
        )
        return result

    @staticmethod
    def load_questions(config: EvaluationConfig) -> list[EvaluationQuestion]:
        if not config.questions_file:
            raise ValueError("generated questions require a generator")
        return load_questions(config.questions_file)


__all__ = ("EvaluationAgent", "build_evaluation_deep_agent", "load_config")
