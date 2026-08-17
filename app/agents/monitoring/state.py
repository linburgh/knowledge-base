"""自主监控 Deep Agent 的会话状态、证据工作区与可信上下文。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.common import utils
from app.core.common.exception import BusiException

from .models import AnalysisTimeRange
from .workspace import EvidenceWorkspace

MONITORING_TIMEZONE = "Asia/Shanghai"


@dataclass(slots=True)
class MonitoringSession:
    """保存单轮 Agent 的可信依赖和实际工具事实，不暴露给模型参数。"""

    question: str
    trusted_context: dict[str, Any]
    registry: Any
    runtime: Any
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    time_range: AnalysisTimeRange | None = None
    workspace: EvidenceWorkspace = field(default_factory=EvidenceWorkspace)
    _facts_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def store_fact(self, name: str, result: dict[str, Any]) -> dict[str, Any]:
        """在并行工具之间共享整轮上下文预算，避免每个工具各返回上限数量。"""
        async with self._facts_lock:
            used = sum(len(item.get("items") or []) for item in self.facts.values())
            remaining = max(self.runtime.max_context_items - used, 0)
            result = self.workspace.add_result(result)
            items = list(result.get("items") or [])
            per_source_limit = max(self.runtime.max_context_items // 5, 1)
            allowed = min(remaining, per_source_limit)
            compact = {
                **result,
                "items": items[:allowed],
                "items_truncated": len(items) > allowed,
            }
            previous = self.facts.get(name) or {}
            previous_items = list(previous.get("items") or [])
            merged = {str(item.get("id") or ""): item for item in [*previous_items, *compact["items"]]}
            compact["items"] = list(merged.values())[:allowed]
            compact["items_truncated"] = bool(compact.get("items_truncated")) or len(merged) > allowed
            self.facts[name] = compact
            return compact

    def require_time_range(self) -> AnalysisTimeRange:
        """返回服务端预先解析的可信时间窗口，模型不得提供或覆盖。"""
        if self.time_range is None:
            raise BusiException("监控查询缺少可信时间范围")
        timezone = ZoneInfo(MONITORING_TIMEZONE)
        start = self.time_range.start.astimezone(timezone)
        end = self.time_range.end.astimezone(timezone)
        now = utils.to_china_standard_time(utils.utc_now())
        if start >= end or end - start > timedelta(days=7):
            raise BusiException("监控查询时间范围无效")
        if end > now + timedelta(minutes=5):
            raise BusiException("监控查询时间不能超过当前时间")
        return self.time_range


@dataclass(frozen=True, slots=True)
class MonitoringHarnessContext:
    """通过 ToolRuntime 注入且不暴露为模型参数的可信会话。"""
    # Any 用于防止工具 Schema 生成器展开 Session 并向模型暴露可信字段。
    session: Any


__all__ = ("MonitoringHarnessContext", "MonitoringSession")
