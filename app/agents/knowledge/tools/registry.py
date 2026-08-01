from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.common.exception import BusiException
from app.schemas.agent import AgentContext, ToolCall, ToolName, ToolResult

ToolHandler = Callable[[ToolCall, AgentContext], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: ToolName
    handler: ToolHandler
    input_schema: type[Any]
    output_schema: type[Any]
    read_only: bool = True
    requires_scope: bool = True


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: ToolName,
        handler: ToolHandler,
        *,
        input_schema: type[Any] = dict,
        output_schema: type[Any] = dict,
    ) -> None:
        if name in self._definitions:
            raise ValueError(f"Tool already registered: {name}")
        self._definitions[name] = ToolDefinition(
            name=name,
            handler=handler,
            input_schema=input_schema,
            output_schema=output_schema,
        )

    def get(self, name: str) -> ToolHandler:
        try:
            return self._definitions[name].handler
        except KeyError as exc:
            raise BusiException("工具未注册", status_code=403) from exc

    def names(self) -> set[str]:
        return set(self._definitions)

    def definition(self, name: str) -> ToolDefinition:
        self.get(name)
        return self._definitions[name]


def build_default_registry() -> ToolRegistry:
    from app.schemas.agent import (
        CitationToolInput,
        CitationToolOutput,
        HistoryToolInput,
        HistoryToolOutput,
        RetrievalToolInput,
        RetrievalToolOutput,
    )

    from .citations import build_citations_result
    from .history import load_conversation_history_result
    from .retrieval import retrieve_knowledge_result

    registry = ToolRegistry()
    registry.register(
        "retrieve_knowledge",
        retrieve_knowledge_result,
        input_schema=RetrievalToolInput,
        output_schema=RetrievalToolOutput,
    )
    registry.register(
        "load_conversation_history",
        load_conversation_history_result,
        input_schema=HistoryToolInput,
        output_schema=HistoryToolOutput,
    )
    registry.register(
        "build_citations",
        build_citations_result,
        input_schema=CitationToolInput,
        output_schema=CitationToolOutput,
    )
    return registry


__all__ = ("ToolDefinition", "ToolHandler", "ToolRegistry", "build_default_registry")
