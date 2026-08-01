from __future__ import annotations

import ast
from pathlib import Path

from app.agents.evaluation.tools.registry import EvaluationToolRegistry
from app.agents.knowledge.tools.registry import ToolRegistry
from app.agents.monitoring.tools.registry import MonitoringToolRegistry

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "app" / "agents"


def test_agent_registries_do_not_share_mutable_state() -> None:
    knowledge = ToolRegistry()
    evaluation = EvaluationToolRegistry()
    monitoring = MonitoringToolRegistry()

    async def handler(*args, **kwargs):
        del args, kwargs
        return None

    knowledge.register("knowledge_only", handler)
    evaluation.register("evaluation_only", handler)
    monitoring.register("monitoring_only", handler)

    assert knowledge.names() == {"knowledge_only"}
    assert evaluation.names() == {"evaluation_only"}
    assert monitoring.names() == {"monitoring_only"}


def test_cross_agent_imports_only_use_public_knowledge_protocol() -> None:
    allowed_public_module = "app.agents.knowledge"
    for source_agent in ("evaluation", "monitoring"):
        for path in (AGENT_ROOT / source_agent).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if not node.module.startswith("app.agents."):
                    continue
                target_agent = node.module.split(".")[2]
                if target_agent == source_agent:
                    continue
                assert node.module == allowed_public_module, (
                    f"{path.relative_to(ROOT)} 跨 Agent 导入了私有模块 {node.module}"
                )


def test_monitoring_does_not_import_evaluation_runtime_or_graph() -> None:
    forbidden = (
        "app.agents.evaluation.graph",
        "app.agents.evaluation.runtime",
        "app.agents.evaluation.state",
        "app.agents.evaluation.agent",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (AGENT_ROOT / "monitoring").rglob("*.py")
    )
    assert not any(module in source for module in forbidden)
