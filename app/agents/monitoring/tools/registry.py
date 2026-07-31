from __future__ import annotations


class MonitoringToolRegistry:
    """监控 Agent 只接收 Service 注入的只读、结构化工具。"""

    def __init__(self) -> None:
        self._tools = {}

    def register(self, name: str, handler) -> None:
        if name in self._tools:
            raise ValueError(f"duplicate monitoring tool: {name}")
        self._tools[name] = handler

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    async def invoke(self, name: str, **kwargs):
        if name not in self._tools:
            raise KeyError(f"monitoring tool is not registered: {name}")
        return await self._tools[name](**kwargs)
