from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.monitoring import (
    MonitoringToolDefinition,
    MonitoringToolInput,
    MonitoringToolOutput,
)

MonitoringToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class MonitoringToolRegistry:
    """监控 Agent 只接收 Service 注入的只读、结构化工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, MonitoringToolHandler] = {}
        self._definitions: dict[str, MonitoringToolDefinition] = {}

    def register(self, name: str, handler: MonitoringToolHandler) -> None:
        if name in self._tools:
            raise ValueError(f"duplicate monitoring tool: {name}")
        self._tools[name] = handler
        self._definitions[name] = MonitoringToolDefinition(name=name)

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def get(self, name: str) -> MonitoringToolHandler:
        if name not in self._tools:
            raise KeyError(f"monitoring tool is not registered: {name}")
        return self._tools[name]

    async def invoke(self, name: str, **kwargs):
        payload = MonitoringToolInput.model_validate(kwargs)
        result = await self.get(name)(**payload.model_dump())
        return MonitoringToolOutput.model_validate(result).model_dump()

    def definition(self, name: str) -> MonitoringToolDefinition:
        self.get(name)
        return self._definitions[name]


__all__ = ("MonitoringToolHandler", "MonitoringToolRegistry")
