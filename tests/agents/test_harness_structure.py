from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "app" / "agents"
AGENTS = ("knowledge", "evaluation", "monitoring")


@pytest.mark.parametrize("agent_name", AGENTS)
def test_each_agent_has_complete_harness_structure(agent_name: str) -> None:
    root = AGENT_ROOT / agent_name
    for relative_path in (
        "__init__.py",
        "agent.py",
        "runtime.py",
        "policies.py",
        "tools/__init__.py",
        "tools/registry.py",
    ):
        assert (root / relative_path).is_file(), f"{agent_name} 缺少 {relative_path}"
    skills = list((root / "skills").glob("*/SKILL.md"))
    assert skills, f"{agent_name} 至少需要一个 Skill"
    assert all(len(path.read_text(encoding="utf-8").strip()) >= 100 for path in skills)


def test_agent_root_does_not_contain_shared_runtime_or_tools() -> None:
    forbidden = {"agent.py", "runtime.py", "policies.py", "tools", "skills"}
    assert not forbidden.intersection(path.name for path in AGENT_ROOT.iterdir())


def test_agents_do_not_import_other_agent_private_modules() -> None:
    allowed_public = {"app.agents.knowledge"}
    for agent_name in AGENTS:
        for path in (AGENT_ROOT / agent_name).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if not node.module.startswith("app.agents."):
                    continue
                target_agent = node.module.split(".")[2]
                if target_agent == agent_name:
                    continue
                assert node.module in allowed_public, (
                    f"{path.relative_to(ROOT)} 导入了其他 Agent 私有模块 {node.module}"
                )


def test_monitoring_service_only_keeps_tool_compatibility_import() -> None:
    service = (ROOT / "app/core/services/monitoring_analysis_tools.py").read_text(
        encoding="utf-8"
    )
    assert "async def query_" not in service
    assert "app.agents.monitoring.tools.queries" in service
