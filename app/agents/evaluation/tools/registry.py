from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.common.exception import BusiException
from app.schemas.evaluation import EvaluationAgentContext

EvaluationToolHandler = Callable[[dict[str, Any], EvaluationAgentContext], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class EvaluationToolDefinition:
    name: str
    handler: EvaluationToolHandler
    read_only: bool = True


class EvaluationToolRegistry:
    """评测 Agent 的显式只读工具注册表。"""

    def __init__(self) -> None:
        self._tools: dict[str, EvaluationToolDefinition] = {}

    def register(self, name: str, handler: EvaluationToolHandler) -> None:
        if name in self._tools:
            raise ValueError(f"duplicate evaluation tool: {name}")
        self._tools[name] = EvaluationToolDefinition(name=name, handler=handler)

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def get(self, name: str) -> EvaluationToolDefinition:
        if name not in self._tools:
            raise BusiException("评测工具未注册", status_code=403)
        return self._tools[name]

    async def invoke(
        self,
        name: str,
        payload: dict[str, Any],
        context: EvaluationAgentContext,
    ) -> Any:
        return await self.get(name).handler(payload, context)


def build_default_registry() -> EvaluationToolRegistry:
    from .knowledge import call_knowledge_agent

    registry = EvaluationToolRegistry()
    registry.register("call_knowledge_agent", call_knowledge_agent)
    return registry


__all__ = (
    "EvaluationToolDefinition",
    "EvaluationToolHandler",
    "EvaluationToolRegistry",
    "build_default_registry",
)
