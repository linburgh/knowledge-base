from __future__ import annotations


class EvaluationToolRegistry:
    """评测工具显式注册表，默认不注册写入或直接 LLM 工具。"""

    def __init__(self) -> None:
        self._tools = {}

    def register(self, name: str, handler) -> None:
        if name in self._tools:
            raise ValueError(f"duplicate evaluation tool: {name}")
        self._tools[name] = handler

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)
