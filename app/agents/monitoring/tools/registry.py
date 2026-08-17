"""自主监控 Agent 的显式工具注册、协议校验与展示元数据边界。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.monitoring import (
    MonitoringToolDefinition,
    MonitoringToolInput,
    MonitoringToolOutput,
)

from ..presentation import presentation_for_tool

MonitoringToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class MonitoringToolRegistry:
    """监控 Agent 只接收 Service 注入的只读、结构化工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, MonitoringToolHandler] = {}
        self._definitions: dict[str, MonitoringToolDefinition] = {}

    def register(self, name: str, handler: MonitoringToolHandler) -> None:
        """注册只读处理器并绑定对应事实展示定义。"""
        if name in self._tools:
            raise ValueError(f"duplicate monitoring tool: {name}")
        self._tools[name] = handler
        presentation = presentation_for_tool(name)
        self._definitions[name] = MonitoringToolDefinition(
            name=name,
            fact_type=presentation.get("fact_type"),
            presentation=presentation,
        )

    def names(self) -> frozenset[str]:
        """返回不可变的已注册工具名称集合。"""
        return frozenset(self._tools)

    def get(self, name: str) -> MonitoringToolHandler:
        """取得工具处理器，未知名称立即拒绝。"""
        if name not in self._tools:
            raise KeyError(f"monitoring tool is not registered: {name}")
        return self._tools[name]

    async def invoke(self, name: str, **kwargs):
        """校验输入、调用处理器并按结构化输出协议返回结果。"""
        payload = MonitoringToolInput.model_validate(kwargs)
        result = await self.get(name)(**payload.model_dump(exclude_defaults=True))
        definition = self.definition(name)
        return MonitoringToolOutput.model_validate(
            {
                **result,
                "fact_type": definition.fact_type,
                "presentation": definition.presentation,
            }
        ).model_dump()

    def definition(self, name: str) -> MonitoringToolDefinition:
        """返回已注册工具的事实类型与展示元数据。"""
        self.get(name)
        return self._definitions[name]


__all__ = ("MonitoringToolHandler", "MonitoringToolRegistry")
