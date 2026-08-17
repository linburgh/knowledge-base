"""自主监控调查的证据去重、容量限制与查询签名工作区。"""

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
        """为工具名称和规范化参数生成稳定查询摘要。"""
        serialized = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(f"{name}:{serialized}".encode()).hexdigest()

    def has_query(self, name: str, arguments: dict[str, Any]) -> bool:
        """判断相同工具及参数是否已成功查询。"""
        return self.signature(name, arguments) in self.query_signatures

    def record_query(self, name: str, arguments: dict[str, Any]) -> None:
        """登记成功查询签名，阻止模型无意义重复调用。"""
        self.query_signatures.add(self.signature(name, arguments))

    def add_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """接收带有效标识的事实，并按工作区容量裁剪结果。"""
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
        """返回不包含事实正文的工作区统计信息。"""
        return {
            "fact_count": len(self.facts),
            "relation_count": len(self.relations),
            "query_count": len(self.query_signatures),
            "truncated": self.truncated,
        }


__all__ = ("EvidenceWorkspace",)
