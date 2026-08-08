from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from app.core.common.exception import BusiException

from ..state import EvaluationHarnessContext


def _compact_result(item) -> dict[str, Any]:
    return {
        "case_no": item.case_no,
        "question": item.question,
        "status": item.status,
        "termination_reason": item.termination_reason,
        "citation_count": item.citation_count,
        "hit_count": item.hit_count,
        "duration_ms": item.duration_ms,
        "error_code": item.error_code,
        "answer_excerpt": (item.answer or "")[:1000],
    }


async def _run_cases(session, selected: list[int], *, review: bool) -> dict[str, Any]:
    await session.runtime.check_cancelled()
    questions = [session.questions[case_no - 1] for case_no in selected]
    results = await session.runtime.run(
        questions,
        lambda case_no, question: session.executor.execute(
            case_no,
            question,
            config=session.config,
            context=session.trusted_context,
            runtime=session.runtime,
        ),
        monitoring_fields=session.trusted_context.monitoring_fields,
        case_numbers=selected,
    )
    for item in results:
        previous = session.results.get(item.case_no)
        if review and previous is not None:
            item.metadata = {
                **item.metadata,
                "review_round": session.review_round,
                "previous_status": previous.status,
                "previous_termination_reason": previous.termination_reason,
            }
        session.results[item.case_no] = item
    return {
        "executed_case_numbers": selected,
        "review_round": session.review_round,
        "results": [_compact_result(item) for item in results],
        "metrics": session.metrics().model_dump(mode="json"),
    }


@tool
async def execute_evaluation_cases(
    *,
    runtime: ToolRuntime[EvaluationHarnessContext],
) -> dict[str, Any]:
    """首次执行全部评测问题。每次运行只能调用一次，不接收题号或权限参数。"""
    session = runtime.context.session
    if session.results:
        raise BusiException("自主评测初次执行工具不能重复调用")
    return await _run_cases(
        session,
        list(range(1, len(session.questions) + 1)),
        review=False,
    )


@tool
async def retry_evaluation_cases(
    case_numbers: list[int],
    *,
    runtime: ToolRuntime[EvaluationHarnessContext],
) -> dict[str, Any]:
    """复核指定评测题目。只能在全量初次执行后调用，并受最大复核轮次限制。"""
    session = runtime.context.session
    if not session.all_cases_completed():
        raise BusiException("自主评测尚未完成全部初次问题")
    selected = list(dict.fromkeys(case_numbers))
    valid = set(range(1, len(session.questions) + 1))
    if not selected or any(case_no not in valid for case_no in selected):
        raise BusiException("评测 Agent 选择了无效题号")
    if session.review_round >= session.config.max_review_rounds:
        raise BusiException("自主评测已达到最大复核轮次")
    session.review_round += 1
    session.reviewed_case_numbers.extend(
        case_no for case_no in selected if case_no not in session.reviewed_case_numbers
    )
    return await _run_cases(session, selected, review=True)


@tool
async def inspect_evaluation_results(
    *,
    runtime: ToolRuntime[EvaluationHarnessContext],
) -> dict[str, Any]:
    """查看当前逐题结果、异常样品和确定性指标，用于决定是否需要复核。"""
    session = runtime.context.session
    await session.runtime.check_cancelled()
    results = session.ordered_results()
    anomalies = [item for item in results if item.status != "completed" or item.citation_count == 0]
    return {
        "all_cases_completed": session.all_cases_completed(),
        "completed_case_count": len(results),
        "total_case_count": len(session.questions),
        "review_round": session.review_round,
        "max_review_rounds": session.config.max_review_rounds,
        "metrics": session.metrics().model_dump(mode="json"),
        "anomalies": [_compact_result(item) for item in anomalies[:100]],
        "anomalies_truncated": len(anomalies) > 100,
    }


__all__ = (
    "execute_evaluation_cases",
    "inspect_evaluation_results",
    "retry_evaluation_cases",
)
