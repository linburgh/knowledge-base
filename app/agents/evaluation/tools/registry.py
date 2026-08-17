"""自主评测 Agent 的显式只读工具注册与调用边界。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.common.exception import BusiException
from app.schemas.evaluation import EvaluationAgentContext

EvaluationToolHandler = Callable[[dict[str, Any], EvaluationAgentContext], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class EvaluationToolDefinition:
    """评测工具名称、处理器及只读属性定义。"""
    name: str
    handler: EvaluationToolHandler
    read_only: bool = True


class EvaluationToolRegistry:
    """评测 Agent 的显式只读工具注册表。

    注册表是能力清单，不承担用户授权；每次调用仍须由 Runtime 调用 Policies 校验。
    新增工具时默认只允许只读能力，并同步更新白名单、预算与 Harness 测试。
    """

    def __init__(self) -> None:
        self._tools: dict[str, EvaluationToolDefinition] = {}

    def register(self, name: str, handler: EvaluationToolHandler) -> None:
        """显式注册只读工具，并拒绝重名覆盖。"""
        if name in self._tools:
            raise ValueError(f"duplicate evaluation tool: {name}")
        self._tools[name] = EvaluationToolDefinition(name=name, handler=handler)

    def names(self) -> frozenset[str]:
        """返回不可变的已注册工具名称集合。"""
        return frozenset(self._tools)

    def get(self, name: str) -> EvaluationToolDefinition:
        """返回工具定义；未知工具按权限错误拒绝。"""
        if name not in self._tools:
            raise BusiException("评测工具未注册", status_code=403)
        return self._tools[name]

    async def invoke(
        self,
        name: str,
        payload: dict[str, Any],
        context: EvaluationAgentContext,
    ) -> Any:
        """通过注册定义调用工具；调用前授权由 Runtime 负责。"""
        return await self.get(name).handler(payload, context)


def build_default_registry() -> EvaluationToolRegistry:
    """构建仅允许调用知识问答 Agent 的默认注册表。"""
    from .knowledge import call_knowledge_agent

    # 显式逐项注册，避免通过模块扫描把未审核函数意外暴露给 Agent。
    registry = EvaluationToolRegistry()
    registry.register("call_knowledge_agent", call_knowledge_agent)
    return registry


__all__ = (
    "EvaluationToolDefinition",
    "EvaluationToolHandler",
    "EvaluationToolRegistry",
    "build_default_registry",
)
