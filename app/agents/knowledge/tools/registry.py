"""知识库问答 Agent 的显式工具注册表与结构化协议定义。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.common.exception import BusiException
from app.schemas.agent import AgentContext, ToolCall, ToolName, ToolResult

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

ToolHandler = Callable[[ToolCall, AgentContext], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """单个工具处理器及其输入、输出模型声明。"""
    name: ToolName
    handler: ToolHandler
    input_schema: type[Any]
    output_schema: type[Any]
    read_only: bool = True
    requires_scope: bool = True


class ToolRegistry:
    """仅暴露逐项审核并显式注册的知识库问答工具。"""

    def __init__(self) -> None:
        """初始化空注册表。"""
        self._definitions: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: ToolName,
        handler: ToolHandler,
        *,
        input_schema: type[Any] = dict,
        output_schema: type[Any] = dict,
    ) -> None:
        """注册工具及协议模型，拒绝重名覆盖。"""
        if name in self._definitions:
            raise ValueError(f"Tool already registered: {name}")
        self._definitions[name] = ToolDefinition(
            name=name,
            handler=handler,
            input_schema=input_schema,
            output_schema=output_schema,
        )

    def get(self, name: str) -> ToolHandler:
        """取得已注册处理器；未知工具按权限错误拒绝。"""
        try:
            return self._definitions[name].handler
        except KeyError as exc:
            raise BusiException("工具未注册", status_code=403) from exc

    def names(self) -> set[str]:
        """返回当前显式注册的工具名称集合。"""
        return set(self._definitions)

    def definition(self, name: str) -> ToolDefinition:
        """返回工具的处理器与结构化协议定义。"""
        self.get(name)
        return self._definitions[name]


def build_default_registry() -> ToolRegistry:
    """构建知识问答 Agent 默认的三项只读工具注册表。"""
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
