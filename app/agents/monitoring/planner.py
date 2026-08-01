from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import CONF
from app.core.common import utils
from app.core.common.log import LOG

from .model import build_monitoring_chat_model
from .models import (
    AnalysisIntent,
    AnalysisPlan,
    AnalysisTimeRange,
    StructuredAnalysisPlan,
)
from .planning import (
    MONITORING_TIMEZONE,
    build_plan,
    default_tools_for_intent,
    resolve_time_range,
)
from .policies import READ_ONLY_TOOLS
from .skills import load_skill

PLANNER_SYSTEM_PROMPT = """你是企业自主监控智能体的语义规划器，只负责生成分析计划，不回答问题。
请理解用户真正的监控分析目标，而不是依赖固定关键词。允许的粗粒度意图包括：
platform_health、incident_cause、impact_scope、evidence_review、next_action、
task_diagnosis、period_review、identity、general_analysis。
无法归类的新问题使用 general_analysis，并通过 goal、entities、dimensions 保留完整语义。

允许的只读工具：
- query_health_snapshots：服务、数据库、Worker 和外部依赖健康状态；
- query_alerts：全部生命周期告警；
- query_metrics：错误率、耗时、成功率和其他指标；
- query_events：异常、失败、降级、发布及链路追踪事件；
- query_tasks：任务和评测运行事实。

语言要求：
- 面向中国客户，所有自然语言内容必须使用简体中文；
- goal、time.label 和 uncertainties 必须使用中文完整表达；
- entities 和 dimensions 优先使用中文，只有稳定编码、行业缩写或产品专名可以保留原文；
- 不得为了显得专业而混用不必要的英文。

时间要求：
- 当前时间由用户消息提供，业务时区固定为中国标准时间；
- 昨天是前一自然日；最近一天是滚动24小时；
- 对“昨晚、发布之后、用户反馈很慢那段时间”等表达，尽量给出合理起止时间；
- 无法唯一确定时把原因写入 uncertainties，不得伪造精确时间；
- 未指定时间时 start/end 留空，由系统继承会话默认范围。

不得输出租户、用户、角色、权限或任何写操作工具。required_tools 只填写上述只读工具。
"""


class MonitoringPlanner(Protocol):
    async def plan(
        self,
        question: str,
        *,
        default_time_range: str,
        now: datetime | None = None,
    ) -> AnalysisPlan: ...


class RuleBasedMonitoringPlanner:
    async def plan(
        self,
        question: str,
        *,
        default_time_range: str,
        now: datetime | None = None,
    ) -> AnalysisPlan:
        return build_plan(question, default_time_range=default_time_range, now=now)


class UnavailableMonitoringPlanner:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def plan(
        self,
        question: str,
        *,
        default_time_range: str,
        now: datetime | None = None,
    ) -> AnalysisPlan:
        del question, default_time_range, now
        raise self.error


def _normalize_intent(value: str) -> AnalysisIntent:
    try:
        return AnalysisIntent(value.strip().lower())
    except ValueError:
        return AnalysisIntent.GENERAL_ANALYSIS


def _normalize_time_range(
    output: StructuredAnalysisPlan,
    *,
    question: str,
    default_time_range: str,
    now: datetime,
    uncertainties: list[str],
) -> AnalysisTimeRange:
    timezone = ZoneInfo(MONITORING_TIMEZONE)
    start = output.time.start
    end = output.time.end
    if start is not None and end is not None:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone)
        start = start.astimezone(timezone)
        end = end.astimezone(timezone)
        if start < end <= now + timedelta(minutes=5) and end - start <= timedelta(days=7):
            return AnalysisTimeRange(
                start=start,
                end=end,
                timezone=MONITORING_TIMEZONE,
                label=output.time.label or output.time.expression or "指定时间",
                source="question",
            )
        uncertainties.append("模型时间范围未通过边界校验，已使用本地时间解析")
    elif start is not None or end is not None:
        uncertainties.append("模型时间范围缺少起点或终点，已使用本地时间解析")

    expression = output.time.expression or question
    return resolve_time_range(
        expression,
        default_time_range=default_time_range,
        now=now,
    )


class StructuredOutputMonitoringPlanner:
    def __init__(self, model: Any, *, timeout_seconds: float = 8.0) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def plan(
        self,
        question: str,
        *,
        default_time_range: str,
        now: datetime | None = None,
    ) -> AnalysisPlan:
        timezone = ZoneInfo(MONITORING_TIMEZONE)
        current = now or utils.utc_now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone)
        current = current.astimezone(timezone)
        analysis_skill, _ = load_skill("monitoring-analysis")
        structured_model = self.model.with_structured_output(
            StructuredAnalysisPlan,
            method="function_calling",
        )
        output = await asyncio.wait_for(
            structured_model.ainvoke(
                [
                    SystemMessage(content=f"{PLANNER_SYSTEM_PROMPT}\n\n{analysis_skill}"),
                    HumanMessage(
                        content=(
                            f"当前时间：{current.isoformat()}\n"
                            f"会话默认时间：{default_time_range}\n"
                            f"用户问题：{question}"
                        )
                    ),
                ]
            ),
            timeout=self.timeout_seconds,
        )
        if not isinstance(output, StructuredAnalysisPlan):
            output = StructuredAnalysisPlan.model_validate(output)

        uncertainties = list(output.uncertainties)
        intent = _normalize_intent(output.intent)
        if intent == AnalysisIntent.GENERAL_ANALYSIS and output.intent != intent.value:
            uncertainties.append("检测到未登记的分析意图，已按通用分析处理")

        tools = []
        for name in output.required_tools:
            if name not in READ_ONLY_TOOLS:
                uncertainties.append("检测到未授权工具，已从查询计划中移除")
                continue
            if name not in tools:
                tools.append(name)
        if intent == AnalysisIntent.IDENTITY:
            tools = []
        elif not tools:
            tools = list(default_tools_for_intent(intent))
            uncertainties.append("模型未返回合法只读工具，已补充安全默认查询计划")

        time_range = _normalize_time_range(
            output,
            question=question,
            default_time_range=default_time_range,
            now=current,
            uncertainties=uncertainties,
        )
        return AnalysisPlan(
            intent=intent,
            time_range=time_range,
            tools=tuple(tools),
            goal=output.goal.strip(),
            time_expression=output.time.expression,
            entities=tuple(dict.fromkeys(output.entities)),
            dimensions=tuple(dict.fromkeys(output.dimensions)),
            uncertainties=tuple(uncertainties),
            confidence=output.confidence,
            planning_mode="llm",
        )


class ResilientMonitoringPlanner:
    def __init__(
        self, primary: MonitoringPlanner, fallback: MonitoringPlanner | None = None
    ) -> None:
        self.primary = primary
        self.fallback = fallback or RuleBasedMonitoringPlanner()

    async def plan(
        self,
        question: str,
        *,
        default_time_range: str,
        now: datetime | None = None,
    ) -> AnalysisPlan:
        try:
            return await self.primary.plan(
                question,
                default_time_range=default_time_range,
                now=now,
            )
        except Exception as exc:
            LOG.warning("自主监控Agent planner fallback error={}", type(exc).__name__)
            fallback = await self.fallback.plan(
                question,
                default_time_range=default_time_range,
                now=now,
            )
            return replace(
                fallback,
                uncertainties=(
                    *fallback.uncertainties,
                    "模型语义规划不可用，已使用有限规则降级规划",
                ),
                planning_mode="fallback",
                planning_error=type(exc).__name__,
            )


def build_monitoring_planner(model: Any | None = None) -> MonitoringPlanner:
    try:
        planner_model = model if model is not None else build_monitoring_chat_model()
    except Exception as exc:
        return ResilientMonitoringPlanner(UnavailableMonitoringPlanner(exc))
    primary = StructuredOutputMonitoringPlanner(
        planner_model,
        timeout_seconds=min(float(CONF.chat.timeout_seconds), 8.0),
    )
    return ResilientMonitoringPlanner(primary)


__all__ = (
    "MonitoringPlanner",
    "PLANNER_SYSTEM_PROMPT",
    "ResilientMonitoringPlanner",
    "RuleBasedMonitoringPlanner",
    "StructuredOutputMonitoringPlanner",
    "UnavailableMonitoringPlanner",
    "build_monitoring_planner",
)
