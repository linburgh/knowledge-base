from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any


def _value(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    return "" if value is None else str(value)


def correlate_alert_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按稳定业务字段收敛告警；相似性只作为关联证据，不直接认定重复写入。"""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        key = (
            _value(item, "metric_code"),
            _value(item, "resource_type"),
            _value(item, "resource_code"),
            _value(item, "scope_key"),
        )
        groups[key].append(item)

    results = []
    for key, members in groups.items():
        times = [
            value
            for item in members
            if isinstance((value := item.get("last_fired_at")), datetime)
        ]
        spread_seconds = (
            int((max(times) - min(times)).total_seconds()) if len(times) > 1 else 0
        )
        rule_ids = {_value(item, "rule_id") for item in members if _value(item, "rule_id")}
        same_signature = len(members) > 1 and bool(key[0]) and bool(key[3])
        member_ids = sorted(str(item.get("id") or "") for item in members)
        group_id = hashlib.sha256("|".join(member_ids).encode()).hexdigest()[:12]
        results.append(
            {
                "id": f"alert-correlation-{group_id}",
                "evidence_type": "alert_correlation",
                "evidence_type_name": "告警关联",
                "title": members[0].get("title") or members[0].get("alert_title") or "告警分组",
                "summary": (
                    f"{len(members)} 条告警具有相同指标与作用范围，涉及 {len(rule_ids)} 条规则"
                    if same_signature
                    else f"{len(members)} 条告警存在部分共同字段"
                ),
                "status": "likely_duplicate" if same_signature and spread_seconds <= 300 else "related",
                "status_name": (
                    "高度相似" if same_signature and spread_seconds <= 300 else "存在关联"
                ),
                "member_count": len(members),
                "member_ids": member_ids,
                "common_metric_name": members[0].get("metric_name") or "未配置中文名称",
                "common_resource_name": members[0].get("resource_name") or "暂无",
                "time_spread_seconds": spread_seconds,
                "rule_count": len(rule_ids),
                "judgment_boundary": "字段与时间相似只能说明高度相关，不能单独证明数据库重复写入。",
            }
        )
    return results


__all__ = ("correlate_alert_items",)
