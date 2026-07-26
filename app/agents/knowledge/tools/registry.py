from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.common.exception import BusiException
from app.schemas.agent import AgentContext, ToolCall, ToolName, ToolResult

ToolHandler = Callable[[ToolCall, AgentContext], Awaitable[ToolResult]]


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: ToolName, handler: ToolHandler) -> None:
        if name in self._handlers:
            raise ValueError(f"Tool already registered: {name}")
        self._handlers[name] = handler

    def get(self, name: str) -> ToolHandler:
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise BusiException("工具未注册", status_code=403) from exc

    def names(self) -> set[str]:
        return set(self._handlers)


def build_default_registry() -> ToolRegistry:
    from .citations import build_citations_result
    from .history import load_conversation_history_result
    from .retrieval import retrieve_knowledge_result

    registry = ToolRegistry()
    registry.register("retrieve_knowledge", retrieve_knowledge_result)
    registry.register("load_conversation_history", load_conversation_history_result)
    registry.register("build_citations", build_citations_result)
    return registry


__all__ = ("ToolHandler", "ToolRegistry", "build_default_registry")
