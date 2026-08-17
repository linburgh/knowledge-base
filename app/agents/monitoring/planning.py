"""自主监控问题的确定性意图识别、时间解析与兜底计划。"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.common import utils

from .models import AnalysisIntent, AnalysisPlan, AnalysisTimeRange

MONITORING_TIMEZONE = "Asia/Shanghai"

_ROLLING_WINDOWS = {
    "15m": (timedelta(minutes=15), "最近15分钟"),
    "1h": (timedelta(hours=1), "最近1小时"),
    "6h": (timedelta(hours=6), "最近6小时"),
    "24h": (timedelta(hours=24), "最近24小时"),
    "7d": (timedelta(days=7), "最近7天"),
}

_TOOL_PLANS = {
    AnalysisIntent.PLATFORM_HEALTH: (
        "query_health_snapshots",
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
    ),
    AnalysisIntent.INCIDENT_CAUSE: (
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
    ),
    AnalysisIntent.IMPACT_SCOPE: ("query_alerts", "query_events", "query_tasks"),
    AnalysisIntent.EVIDENCE_REVIEW: ("query_alerts", "query_metrics", "query_events"),
    AnalysisIntent.NEXT_ACTION: (
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
    ),
    AnalysisIntent.TASK_DIAGNOSIS: ("query_tasks", "query_events"),
    AnalysisIntent.PERIOD_REVIEW: (
        "query_health_snapshots",
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
    ),
    AnalysisIntent.GENERAL_ANALYSIS: (
        "query_health_snapshots",
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
    ),
    AnalysisIntent.IDENTITY: (),
}


def detect_intent(question: str) -> AnalysisIntent:
    """按稳定关键词识别基础意图，供模型规划失败时兜底。"""
    normalized = "".join(question.lower().split())
    if any(marker in normalized for marker in ("你是谁", "介绍一下自己", "介绍下自己", "自我介绍")):
        return AnalysisIntent.IDENTITY
    if any(marker in normalized for marker in ("正常吗", "是否正常", "运行情况", "健康", "稳定吗")):
        return AnalysisIntent.PLATFORM_HEALTH
    if any(marker in normalized for marker in ("为什么", "原因", "根因", "怎么触发")):
        return AnalysisIntent.INCIDENT_CAUSE
    if any(marker in normalized for marker in ("影响哪些", "影响范围", "影响了什么")):
        return AnalysisIntent.IMPACT_SCOPE
    if any(marker in normalized for marker in ("直接证据", "哪些证据", "证据来源", "依据")):
        return AnalysisIntent.EVIDENCE_REVIEW
    if any(marker in normalized for marker in ("下一步", "怎么处理", "如何处理", "检查什么")):
        return AnalysisIntent.NEXT_ACTION
    if "任务" in normalized and any(
        marker in normalized for marker in ("失败", "异常", "情况", "哪些")
    ):
        return AnalysisIntent.TASK_DIAGNOSIS
    return AnalysisIntent.PERIOD_REVIEW


def _local_now(now: datetime | None) -> datetime:
    """将当前时间规范化为中国标准时间。"""
    current = now or utils.utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo(MONITORING_TIMEZONE))
    return utils.to_china_standard_time(current)


def _natural_day(day, label: str) -> AnalysisTimeRange:
    """构造指定自然日的左闭右开查询窗口。"""
    timezone = ZoneInfo(MONITORING_TIMEZONE)
    start = datetime.combine(day, time.min, tzinfo=timezone)
    return AnalysisTimeRange(
        start=start,
        end=start + timedelta(days=1),
        timezone=MONITORING_TIMEZONE,
        label=label,
        source="question",
    )


def resolve_time_range(
    question: str,
    *,
    default_time_range: str = "1h",
    now: datetime | None = None,
) -> AnalysisTimeRange:
    """解析受支持的时间表达，并限制在服务端允许查询的范围。"""
    current = _local_now(now)
    normalized = "".join(question.lower().split())
    time_limitation = None
    if "昨晚" in normalized:
        start = datetime.combine(
            current.date() - timedelta(days=1),
            time(hour=18),
            tzinfo=current.tzinfo,
        )
        planned_end = datetime.combine(
            current.date(),
            time(hour=6),
            tzinfo=current.tzinfo,
        )
        return AnalysisTimeRange(
            start=start,
            end=min(current, planned_end),
            timezone=MONITORING_TIMEZONE,
            label="昨晚",
            source="question",
        )
    if "昨天" in normalized:
        return _natural_day(current.date() - timedelta(days=1), "昨天")
    if "今天" in normalized:
        start = datetime.combine(current.date(), time.min, tzinfo=current.tzinfo)
        return AnalysisTimeRange(
            start=start,
            end=current,
            timezone=MONITORING_TIMEZONE,
            label="今天",
            source="question",
        )

    date_match = re.search(
        r"(?P<year>20\d{2})[-年/](?P<month>\d{1,2})[-月/](?P<day>\d{1,2})日?", normalized
    )
    if date_match:
        try:
            day = datetime(
                int(date_match.group("year")),
                int(date_match.group("month")),
                int(date_match.group("day")),
            ).date()
        except ValueError:
            time_limitation = "问题中的日期无效，已使用会话默认时间范围"
        else:
            return _natural_day(day, day.strftime("%Y年%m月%d日"))

    rolling_markers = (
        (("最近15分钟", "近15分钟"), "15m"),
        (("最近一小时", "最近1小时", "近一小时", "近1小时"), "1h"),
        (("最近六小时", "最近6小时", "近六小时", "近6小时"), "6h"),
        (("最近一天", "最近24小时", "近一天", "近24小时"), "24h"),
        (("最近七天", "最近7天", "近七天", "近7天"), "7d"),
    )
    for markers, code in rolling_markers:
        if any(marker in normalized for marker in markers):
            duration, label = _ROLLING_WINDOWS[code]
            return AnalysisTimeRange(
                start=current - duration,
                end=current,
                timezone=MONITORING_TIMEZONE,
                label=label,
                source="question",
            )

    duration, label = _ROLLING_WINDOWS.get(default_time_range, _ROLLING_WINDOWS["1h"])
    return AnalysisTimeRange(
        start=current - duration,
        end=current,
        timezone=MONITORING_TIMEZONE,
        label=label,
        source="conversation",
        limitation=time_limitation,
    )


def build_plan(
    question: str,
    *,
    default_time_range: str = "1h",
    now: datetime | None = None,
) -> AnalysisPlan:
    """构建无需模型参与的安全兜底调查计划。"""
    intent = detect_intent(question)
    time_range = resolve_time_range(
        question,
        default_time_range=default_time_range,
        now=now,
    )
    return AnalysisPlan(
        intent=intent,
        time_range=time_range,
        tools=_TOOL_PLANS[intent],
        goal=question.strip() or "分析授权范围内的监控运行事实",
        time_expression=time_range.label if time_range.source == "question" else None,
        planning_mode="fallback",
    )


def default_tools_for_intent(intent: AnalysisIntent) -> tuple[str, ...]:
    """返回指定意图默认需要的只读事实工具。"""
    return _TOOL_PLANS.get(intent, _TOOL_PLANS[AnalysisIntent.GENERAL_ANALYSIS])


__all__ = (
    "MONITORING_TIMEZONE",
    "build_plan",
    "default_tools_for_intent",
    "detect_intent",
    "resolve_time_range",
)
