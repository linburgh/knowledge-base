"""自主评测 Agent Harness 的创建、调度、复核与报告收敛入口。"""

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
from app.core.common.structured_output import (
    StructuredOutputRepairResult,
    repair_structured_output,
)
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
    """仅允许读取评测 Skill，拒绝 Harness 的其他文件系统操作。"""
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
        # 官方限制覆盖 Skill 读取、结构化终态等 Harness 工具；逐题知识库调用
        # 仍由 EvaluationRuntime 独立计数，不能把两种预算混为同一口径。
        ToolCallLimitMiddleware(
            run_limit=max(
                config.max_model_calls * 4,
                (config.max_review_rounds + 1) * 2 + 8,
            ),
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
    """将已校验的 Skill 内容映射为 Deep Agent 状态文件。"""
    return {"/skills/analysis/SKILL.md": {"content": content}}


def _agent_tool_traces(result: dict[str, Any]) -> list[AgentToolTrace]:
    """从 Deep Agent 消息中提取 Harness 工具调用轨迹。"""
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
    """统计结果消息中实际产生的模型响应次数。"""
    return sum(getattr(message, "type", None) == "ai" for message in result.get("messages", []))


def _fallback_analysis(
    session: EvaluationSession,
    *,
    reason: str,
) -> EvaluationAgentOutput:
    """模型终态失败时，仅根据已完成逐题结果生成可审计分析。"""
    metrics = session.metrics()
    results = session.ordered_results()
    failures = [item for item in results if item.status != "completed"]
    missing_citations = [
        item for item in results if item.status == "completed" and item.citation_count == 0
    ]
    findings = [f"已完成 {len(results)} 道题的确定性统计，门禁结论为 {metrics.conclusion}。"]
    if failures:
        findings.append(f"其中 {len(failures)} 道题未正常完成。")
    if missing_citations:
        findings.append(f"其中 {len(missing_citations)} 道已完成题目缺少引用。")
    return EvaluationAgentOutput(
        goal="基于已完成逐题结果形成自主评测结论",
        rationale=f"外部模型终态不可用（{reason}），已使用确定性指标和门禁安全收敛。",
        findings=findings,
        recommendations=["请结合失败样品、引用异常和门禁指标进行人工复核。"],
        reviewed_case_numbers=session.reviewed_case_numbers,
        confidence=0.5,
        termination_reason="evidence_insufficient",
    )


class EvaluationAgent:
    """自主评测 Deep Agent Harness 的唯一公开入口。"""

    def __init__(
        self,
        *,
        registry: EvaluationToolRegistry | None = None,
        cancel_check=None,
        agent_factory: Callable[[EvaluationConfig], Any] | None = None,
        structured_output_repair: Callable[..., Any] = repair_structured_output,
    ) -> None:
        """注入显式工具注册表、执行适配器与可替换模型。"""
        self.registry = registry or build_default_registry()
        self.cancel_check = cancel_check
        self.agent_factory = agent_factory
        self.structured_output_repair = structured_output_repair

    async def run(
        self,
        task: EvaluationAgentTask,
        context: EvaluationAgentContext,
    ) -> EvaluationAgentResult:
        """校验上下文并执行一次完整评测、复核和报告生成流程。"""
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
        if self.agent_factory is not None:
            agent_model = None
            agent = self.agent_factory(config)
        else:
            agent_model = build_evaluation_chat_model()
            agent = build_evaluation_deep_agent(config, model=agent_model)
        LOG.info(
            "自主评测Agent start run_id={} kb_id={} question_count={} harness=deepagents",
            trusted_context.run_id,
            config.kb_id,
            len(questions),
        )
        try:
            # 预留报告、门禁和协议校验时间；最终模型超时不能抹掉已经完成的逐题结果。
            convergence_reserve = min(2.0, config.run_timeout_seconds * 0.2)
            agent_timeout = max(0.01, config.run_timeout_seconds - convergence_reserve)
            model_timeout = False
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
                    timeout=agent_timeout,
                )
            except TimeoutError:
                model_timeout = True
                runtime.stop_reason = "model_timeout_converged"
                result_state = {"messages": []}
                LOG.warning(
                    "自主评测Agent model timed out; preserving completed cases "
                    "run_id={} completed_count={}",
                    trusted_context.run_id,
                    len(session.results),
                )
            for item in runtime.partial_results:
                session.results.setdefault(item.case_no, item)
            if not session.all_cases_completed():
                if not model_timeout:
                    raise BusiException("自主评测 Agent 未完成全部初次问题")
                results = session.ordered_results()
                metrics = session.metrics()
                analysis = _fallback_analysis(session, reason="ModelTimeoutPartial")
                report = build_report(config, results, metrics, analysis=analysis)
                report.update(
                    {
                        "summary": "自主评测未在总时限内完成，以下仅为已完成题目的部分结果。",
                        "conclusion": "indeterminate",
                    }
                )
                result = EvaluationAgentResult(
                    case_results=[item.model_dump(mode="json") for item in results],
                    metrics=metrics.model_dump(mode="json"),
                    report=report,
                    conclusion="indeterminate",
                    summary=EvaluationRunSummary(
                        status="failed",
                        termination_reason="timeout",
                        tool_calls=runtime.tool_traces,
                        model_call_count=runtime.model_call_count,
                        duration_ms=int((monotonic() - started) * 1000),
                        limitations=["评测总超时，仅保留已完成题目"],
                        skill_refs=runtime.skill_refs,
                        completed_count=len(results),
                        failed_count=len(questions) - len(results),
                    ),
                )
                LOG.warning(
                    "自主评测Agent partial timeout converged run_id={} "
                    "completed_count={} total_count={}",
                    trusted_context.run_id,
                    len(results),
                    len(questions),
                )
                return result
            runtime.model_call_count = _model_call_count(result_state)
            raw_output = result_state.get("structured_response")
            analysis: EvaluationAgentOutput | None = None
            structured_error: str | None = None
            if raw_output is not None:
                try:
                    analysis = (
                        raw_output
                        if isinstance(raw_output, EvaluationAgentOutput)
                        else EvaluationAgentOutput.model_validate(raw_output)
                    )
                except ValueError:
                    structured_error = "StructuredOutputInvalid"
            elif not model_timeout:
                structured_error = "StructuredOutputMissing"

            if structured_error is not None:
                repair_model = agent_model
                if (
                    repair_model is None
                    and self.structured_output_repair is repair_structured_output
                ):
                    try:
                        repair_model = build_evaluation_chat_model()
                    except Exception:
                        LOG.warning(
                            "自主评测Agent structured output repair model unavailable run_id={}",
                            trusted_context.run_id,
                        )
                repair_timeout = min(
                    8.0,
                    max(0.0, config.run_timeout_seconds - (monotonic() - started) - 0.5),
                )
                if (
                    repair_model is None
                    and self.structured_output_repair is repair_structured_output
                ):
                    repair = StructuredOutputRepairResult(
                        value=None,
                        attempted=False,
                        error="RepairModelUnavailable",
                    )
                else:
                    repair = await self.structured_output_repair(
                        model=repair_model,
                        schema=EvaluationAgentOutput,
                        evidence_payload={
                            "goal": "分析本次知识库问答评测结果",
                            "metrics": session.metrics().model_dump(mode="json"),
                            "reviewed_case_numbers": session.reviewed_case_numbers,
                            "cases": [
                                {
                                    "case_no": item.case_no,
                                    "status": item.status,
                                    "citation_count": item.citation_count,
                                    "hit_count": item.hit_count,
                                    "error_code": item.error_code,
                                }
                                for item in session.ordered_results()
                            ],
                        },
                        timeout_seconds=(
                            repair_timeout
                            if runtime.model_call_count < config.max_model_calls
                            else 0.0
                        ),
                        agent_name="evaluation_agent",
                    )
                if repair.attempted:
                    runtime.model_call_count += 1
                if repair.value is not None:
                    analysis = repair.value
                    structured_error = None
                    LOG.info(
                        "自主评测Agent structured output repair succeeded run_id={}",
                        trusted_context.run_id,
                    )
                else:
                    LOG.warning(
                        "自主评测Agent structured output repair unavailable run_id={} reason={}",
                        trusted_context.run_id,
                        repair.error,
                    )

            if analysis is None:
                fallback_reason = "ModelTimeout" if model_timeout else structured_error
                fallback_reason = fallback_reason or "StructuredOutputMissing"
                analysis = _fallback_analysis(session, reason=fallback_reason)
                LOG.warning(
                    "自主评测Agent structured terminal unavailable; "
                    "using deterministic convergence run_id={} reason={}",
                    trusted_context.run_id,
                    fallback_reason,
                )
            else:
                fallback_reason = None
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
                    limitations=(
                        [f"外部模型终态不可用：{fallback_reason}"] if fallback_reason else []
                    ),
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
        except BusiException:
            # 权限、配置和 Agent 业务协议错误由调用方按既有错误语义处理，不能
            # 与外部模型供应商故障混淆成可重试的任务级失败。
            raise
        except Exception as exc:
            # 429、5xx、连接失败等供应商异常也必须形成结构化终态。已完成逐题
            # 结果仍进入失败报告，但门禁结论固定为 indeterminate，不能用部分
            # 样本冒充一次完整评测。
            for item in runtime.partial_results:
                session.results.setdefault(item.case_no, item)
            partial_results = session.ordered_results()
            if partial_results:
                metrics = session.metrics()
                analysis = _fallback_analysis(session, reason="ProviderError")
                report = build_report(config, partial_results, metrics, analysis=analysis)
                report.update(
                    {
                        "summary": "外部模型服务异常，以下仅保留已经完成的逐题结果。",
                        "conclusion": "indeterminate",
                    }
                )
                metric_payload = metrics.model_dump(mode="json")
            else:
                report = {}
                metric_payload = {}
            LOG.opt(exception=exc).error(
                "自主评测Agent provider execution failed run_id={} error_type={}",
                trusted_context.run_id,
                type(exc).__name__,
            )
            result = EvaluationAgentResult(
                case_results=[item.model_dump(mode="json") for item in partial_results],
                metrics=metric_payload,
                report=report,
                conclusion="indeterminate",
                summary=EvaluationRunSummary(
                    status="failed",
                    termination_reason="agent_error",
                    tool_calls=runtime.tool_traces,
                    model_call_count=runtime.model_call_count,
                    duration_ms=int((monotonic() - started) * 1000),
                    limitations=[f"外部模型服务异常：{type(exc).__name__}"],
                    skill_refs=runtime.skill_refs,
                    completed_count=len(partial_results),
                    failed_count=len(questions) - len(partial_results),
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
        """从配置指定文件加载导入型评测问题。"""
        if not config.questions_file:
            raise ValueError("generated questions require a generator")
        return load_questions(config.questions_file)


__all__ = ("EvaluationAgent", "build_evaluation_deep_agent", "load_config")
