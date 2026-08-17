"""知识库问答 Deep Agent 的单次会话状态与可信上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.agent import AgentContext


@dataclass(slots=True)
class KnowledgeSession:
    """单次知识问答 Deep Agent 的可信状态。

    业务工具必须通过这里持有的独立 Runtime 和 Registry 执行。这样官方 Harness
    可以统计 Skill/结构化工具，而项目 Runtime 只统计真实知识库业务工具，两种预算
    不会因 Deep Agent 的内部实现变化而互相挤占。
    """

    trusted_context: AgentContext
    runtime: Any
    retrieved_chunks: dict[int, dict[str, Any]] = field(default_factory=dict)

    def store_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """按分块 ID 保存实际检索事实，重复结果保留首次内容。"""
        for chunk in chunks:
            chunk_id = chunk.get("id")
            if chunk_id is not None:
                self.retrieved_chunks.setdefault(int(chunk_id), chunk)

    def chunks(self) -> list[dict[str, Any]]:
        """返回本轮登记的去重检索分块。"""
        return list(self.retrieved_chunks.values())


@dataclass(frozen=True, slots=True)
class KnowledgeHarnessContext:
    """通过 ToolRuntime 注入可信状态，不暴露为模型工具参数。"""

    session: Any


__all__ = ("KnowledgeHarnessContext", "KnowledgeSession")
