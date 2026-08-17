"""自主评测 Skill 的完整性校验、内容加载与版本标识。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.schemas.agent import AgentSkillRef


def load_evaluation_skill() -> tuple[str, AgentSkillRef]:
    """读取分析 Skill，并返回内容及可审计哈希版本。"""
    path = Path(__file__).parent / "analysis" / "SKILL.md"
    if not path.is_file():
        raise RuntimeError("自主评测 Agent Skill 不存在")
    content = path.read_text(encoding="utf-8").strip()
    if len(content) < 100:
        raise RuntimeError("自主评测 Agent Skill 内容不完整")
    return content, AgentSkillRef(
        name="analysis",
        version=hashlib.sha256(content.encode("utf-8")).hexdigest()[:12],
    )


__all__ = ("load_evaluation_skill",)
