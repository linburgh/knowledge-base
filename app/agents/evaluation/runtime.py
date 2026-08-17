"""自主评测 Agent 的并发、取消、超时、预算与部分结果运行时。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from app.core.common.log import LOG
from app.core.monitoring import emit_gather_event
from app.schemas.agent import AgentSkillRef, AgentToolTrace
from app.schemas.evaluation import EvaluationAgentContext

from .models import CaseResult, EvaluationQuestion
from .policies import authorize_evaluation_tool
from .tools.registry import EvaluationToolRegistry


class EvaluationAgentError(Exception):
    """自主评测运行时可识别异常的基类。"""
    code = "EVALUATION_AGENT_ERROR"


class EvaluationCancelled(EvaluationAgentError):
    """评测任务被上游取消。"""
    code = "EVALUATION_CANCELLED"


class EvaluationBudgetExceeded(EvaluationAgentError):
    """评测工具调用或总执行时间超过预算。"""
    code = "EVALUATION_BUDGET_EXCEEDED"


@dataclass(slots=True)
class EvaluationRuntime:
    """单次评测运行的可变执行边界。

    Runtime 实例不得跨任务复用：计数器、工具轨迹、Skill 版本和部分结果都属于单次
    run。并发控制发生在题目层，工具调用仍统一经过 invoke_tool 进行授权和记账。
    """

    concurrency: int
    timeout_seconds: float
    retry_count: int = 0
    total_timeout_seconds: float = 3600
    max_tool_calls: int = 1000
    cancel_check: Callable[[], Awaitable[bool]] | None = None
    tool_call_count: int = 0
    model_call_count: int = 0
    stop_reason: str = ""
    tool_traces: list[AgentToolTrace] = field(default_factory=list)
    skill_refs: list[AgentSkillRef] = field(default_factory=list)
    partial_results: list[CaseResult] = field(default_factory=list)

    def register_skill(self, skill: AgentSkillRef) -> None:
        """登记本轮加载的 Skill 版本并写入结构化日志。"""
        if all(item.name != skill.name for item in self.skill_refs):
            self.skill_refs.append(skill)
            LOG.info("自主评测Agent skill loaded name={} version={}", skill.name, skill.version)

    async def check_cancelled(self) -> None:
        """调用可选取消探针，并以稳定异常终止任务。"""
        if self.cancel_check is not None and await self.cancel_check():
            self.stop_reason = "cancelled"
            raise EvaluationCancelled("自主评测任务已取消")

    async def invoke_tool(
        self,
        *,
        registry: EvaluationToolRegistry,
        name: str,
        payload: dict[str, Any],
        context: EvaluationAgentContext,
    ):
        """授权、限时执行评测工具并记录成功或失败轨迹。"""
        # 授权必须发生在 Registry 调用之前；Registry 只证明工具已注册，并不代表
        # 当前用户、租户和知识库上下文有权调用它。
        await self.check_cancelled()
        if self.tool_call_count >= self.max_tool_calls:
            self.stop_reason = "budget_exceeded"
            raise EvaluationBudgetExceeded("自主评测工具调用超过预算")
        authorize_evaluation_tool(
            name=name,
            payload=payload,
            context=context,
            registered_tools=registry.names(),
        )
        # 在真正调用前占用预算，失败和超时也计数，防止通过反复失败绕过调用上限。
        self.tool_call_count += 1
        started = monotonic()
        try:
            result = await asyncio.wait_for(
                registry.invoke(name, payload, context),
                timeout=self.timeout_seconds,
            )
            agent_result = getattr(result, "result", None)
            self.tool_traces.append(
                AgentToolTrace(
                    name=name,
                    status="completed",
                    duration_ms=int((monotonic() - started) * 1000),
                    result_count=getattr(agent_result, "hit_count", 0),
                )
            )
            return result
        except TimeoutError:
            self.tool_traces.append(
                AgentToolTrace(
                    name=name,
                    status="timeout",
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code="REQUEST_TIMEOUT",
                )
            )
            raise
        except Exception as exc:
            self.tool_traces.append(
                AgentToolTrace(
                    name=name,
                    status="failed",
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code=type(exc).__name__,
                )
            )
            raise

    async def run(
        self,
        questions: list[EvaluationQuestion],
        execute: Callable[[int, EvaluationQuestion], Awaitable[CaseResult]],
        *,
        monitoring_fields: dict | None = None,
        case_numbers: list[int] | None = None,
    ) -> list[CaseResult]:
        """并发执行指定题目，逐题重试并保留超时前的部分结果。"""
        # 信号量限制的是同时执行的题目数，而不是预先分批；这样既保留吞吐量，
        # 又能让取消检查在每题获取执行槽后及时生效。
        semaphore = asyncio.Semaphore(self.concurrency)
        event_fields = monitoring_fields or {}

        def record_partial(result: CaseResult) -> CaseResult:
            # 每题完成即记录，而不是等待整批 gather 返回。这样整次 Deep Agent
            # 被总超时取消时，已经完成的题目仍可进入失败报告和后续持久化。
            merged = {item.case_no: item for item in self.partial_results}
            merged[result.case_no] = result
            self.partial_results = [merged[number] for number in sorted(merged)]
            return result

        async def one(case_no: int, question: EvaluationQuestion) -> CaseResult:
            async with semaphore:
                await self.check_cancelled()
                LOG.info(
                    "自主评测Agent case start case_no={} source={} question_length={}",
                    case_no,
                    question.source,
                    len(question.question),
                )
                for attempt in range(self.retry_count + 1):
                    await self.check_cancelled()
                    await emit_gather_event(
                        "evaluation.run",
                        "evaluation_case_started",
                        case_no=case_no,
                        attempt=attempt + 1,
                        **event_fields,
                    )
                    try:
                        LOG.info(
                            "自主评测Agent case attempt case_no={} attempt={}",
                            case_no,
                            attempt + 1,
                        )
                        result = await asyncio.wait_for(
                            execute(case_no, question), self.timeout_seconds
                        )
                        LOG.info(
                            "自主评测Agent case finished case_no={} status={}",
                            case_no,
                            result.status,
                        )
                        await emit_gather_event(
                            "evaluation.run",
                            "evaluation_case_completed",
                            case_no=case_no,
                            duration_ms=result.duration_ms,
                            hit_count=result.hit_count,
                            citation_count=result.citation_count,
                            status=result.status,
                            **event_fields,
                        )
                        return record_partial(result)
                    except TimeoutError:
                        LOG.warning(
                            "自主评测Agent case timeout case_no={} attempt={}",
                            case_no,
                            attempt + 1,
                        )
                        if attempt == self.retry_count:
                            result = CaseResult(
                                case_no=case_no,
                                question=question.question,
                                question_source=question.source,
                                question_basis=question.question_basis,
                                status="timeout",
                                termination_reason="timeout",
                                error_code="REQUEST_TIMEOUT",
                            )
                            LOG.info(
                                "自主评测Agent case finished case_no={} status={}",
                                case_no,
                                result.status,
                            )
                            await emit_gather_event(
                                "evaluation.run",
                                "evaluation_case_completed",
                                case_no=case_no,
                                duration_ms=result.duration_ms,
                                hit_count=0,
                                citation_count=0,
                                status="timeout",
                                **event_fields,
                            )
                            return record_partial(result)
                        await emit_gather_event(
                            "evaluation.run",
                            "evaluation_case_retry",
                            case_no=case_no,
                            attempt=attempt + 1,
                            error_category="timeout",
                            **event_fields,
                        )
                    except EvaluationCancelled:
                        raise
                    except EvaluationBudgetExceeded:
                        raise
                    except Exception as exc:
                        LOG.opt(exception=exc).warning(
                            "自主评测Agent case error case_no={} attempt={}",
                            case_no,
                            attempt + 1,
                        )
                        if attempt == self.retry_count:
                            result = CaseResult(
                                case_no=case_no,
                                question=question.question,
                                question_source=question.source,
                                question_basis=question.question_basis,
                                status="error",
                                error_code="CASE_EXECUTION_ERROR",
                                error_message=str(exc)[:500],
                            )
                            LOG.info(
                                "自主评测Agent case finished case_no={} status={}",
                                case_no,
                                result.status,
                            )
                            await emit_gather_event(
                                "evaluation.run",
                                "evaluation_case_completed",
                                case_no=case_no,
                                duration_ms=result.duration_ms,
                                hit_count=0,
                                citation_count=0,
                                status="failed",
                                **event_fields,
                            )
                            return record_partial(result)
                        await emit_gather_event(
                            "evaluation.run",
                            "evaluation_case_retry",
                            case_no=case_no,
                            attempt=attempt + 1,
                            error_category=type(exc).__name__,
                            **event_fields,
                        )
                raise AssertionError("unreachable")

        LOG.info(
            "自主评测Agent runtime start question_count={} concurrency={} timeout_seconds={}",
            len(questions),
            self.concurrency,
            self.timeout_seconds,
        )
        # return_exceptions=True 用于等待同批题目收敛并保留已完成结果。若改成默认
        # fail-fast，首个异常会取消其他协程，部分结果和取消状态将无法可靠持久化。
        numbered_questions = (
            list(zip(case_numbers, questions, strict=True))
            if case_numbers is not None
            else list(enumerate(questions, 1))
        )
        gathered = await asyncio.gather(
            *(one(case_no, question) for case_no, question in numbered_questions),
            return_exceptions=True,
        )
        results = [item for item in gathered if isinstance(item, CaseResult)]
        if case_numbers is None:
            self.partial_results = results
        else:
            # 复核只返回被选择的题目，但取消/预算终止时必须保留此前整批结果。
            merged = {item.case_no: item for item in self.partial_results}
            merged.update({item.case_no: item for item in results})
            self.partial_results = [merged[case_no] for case_no in sorted(merged)]
        # 结构化终止信号优先于普通题目错误向上抛出；普通错误已在 one() 中转换为
        # CaseResult，只有取消和预算耗尽需要终止整次评测。
        cancellation = next(
            (item for item in gathered if isinstance(item, EvaluationCancelled)),
            None,
        )
        if cancellation is not None:
            raise cancellation
        budget_error = next(
            (item for item in gathered if isinstance(item, EvaluationBudgetExceeded)),
            None,
        )
        if budget_error is not None:
            raise budget_error
        LOG.info(
            "自主评测Agent runtime completed question_count={} result_count={}",
            len(questions),
            len(results),
        )
        return results
