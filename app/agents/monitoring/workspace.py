from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvidenceWorkspace:
    """单轮调查证据工作区；仅保存授权工具返回的事实与确定性关系。"""

    max_items: int = 100
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    relations: list[dict[str, Any]] = field(default_factory=list)
    query_signatures: set[str] = field(default_factory=set)
    truncated: bool = False

    @staticmethod
    def signature(name: str, arguments: dict[str, Any]) -> str:
        serialized = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(f"{name}:{serialized}".encode()).hexdigest()

    def has_query(self, name: str, arguments: dict[str, Any]) -> bool:
        return self.signature(name, arguments) in self.query_signatures

    def record_query(self, name: str, arguments: dict[str, Any]) -> None:
        self.query_signatures.add(self.signature(name, arguments))

    def add_result(self, result: dict[str, Any]) -> dict[str, Any]:
        accepted = []
        for item in result.get("items") or []:
            raw_fact_id = item.get("id")
            if raw_fact_id is None or not str(raw_fact_id).strip():
                continue
            fact_id = str(raw_fact_id).strip()
            if fact_id not in self.facts and len(self.facts) >= self.max_items:
                self.truncated = True
                continue
            self.facts[fact_id] = item
            accepted.append(item)
        return {
            **result,
            "items": accepted,
            "items_truncated": bool(result.get("items_truncated")) or self.truncated,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "fact_count": len(self.facts),
            "relation_count": len(self.relations),
            "query_count": len(self.query_signatures),
            "truncated": self.truncated,
        }


__all__ = ("EvidenceWorkspace",)
