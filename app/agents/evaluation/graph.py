from __future__ import annotations

from .agent import EvaluationAgent
from .models import EvaluationConfig, EvaluationQuestion


class EvaluationGraph:
    """保持节点边界的轻量图执行器；可替换为 LangGraph adapter 而不改变协议。"""

    def __init__(self, agent: EvaluationAgent) -> None:
        self.agent = agent

    async def ainvoke(self, config: EvaluationConfig, questions: list[EvaluationQuestion]):
        results, metrics = await self.agent.run(config, questions)
        return {
            "case_results": results,
            "metrics": metrics,
            "conclusion": metrics.conclusion,
            "status": "completed",
        }
