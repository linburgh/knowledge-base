from __future__ import annotations

import hashlib
from pathlib import Path

from app.schemas.agent import AgentSkillRef

_ROOT = Path(__file__).parent


def load_skill(name: str) -> tuple[str, AgentSkillRef]:
    path = _ROOT / name / "SKILL.md"
    if not path.is_file():
        raise RuntimeError(f"自主监控 Agent Skill 不存在: {name}")
    content = path.read_text(encoding="utf-8").strip()
    if len(content) < 100:
        raise RuntimeError(f"自主监控 Agent Skill 内容不完整: {name}")
    return content, AgentSkillRef(
        name=name,
        version=hashlib.sha256(content.encode("utf-8")).hexdigest()[:12],
    )


__all__ = ("load_skill",)
