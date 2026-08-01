from __future__ import annotations

from typing import Any

from app.core.common.exception import BusiException

READ_ONLY_TOOLS = frozenset(
    {
        "query_health_snapshots",
        "query_alerts",
        "query_metrics",
        "query_events",
        "query_tasks",
    }
)
TRUSTED_CONTEXT_FIELDS = frozenset({"tenant_id", "user_id", "role"})


def validate_context(context: dict[str, Any]) -> None:
    role = context.get("role")
    if role not in {"platform_super_admin", "tenant_admin"}:
        raise BusiException("无权使用自主监控分析 Agent", status_code=403)
    if "user_id" in context and not str(context.get("user_id") or "").strip():
        raise BusiException("自主监控 Agent 用户上下文无效", status_code=403)
    if role == "tenant_admin":
        if "tenant_id" in context and context.get("tenant_id") is None:
            raise BusiException("租户监控范围与用户上下文不一致", status_code=403)
        if "scope_key" in context and context.get("scope_key") != "tenant":
            raise BusiException("租户监控范围与用户上下文不一致", status_code=403)
    elif context.get("scope_key") == "tenant" and context.get("tenant_id") is None:
        raise BusiException("租户监控范围缺少租户标识", status_code=403)


def authorize_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    context: dict[str, Any],
    registered_tools: frozenset[str],
) -> None:
    validate_context(context)
    if name not in READ_ONLY_TOOLS or name not in registered_tools:
        raise BusiException("监控分析工具未授权", status_code=403)
    overridden = TRUSTED_CONTEXT_FIELDS.intersection(arguments)
    if overridden:
        raise BusiException(
            f"工具输入不允许覆盖可信上下文字段: {sorted(overridden)[0]}",
            status_code=403,
        )


def redact_context(context: dict[str, Any]) -> dict[str, Any]:
    result = dict(context)
    for key in ("token", "api_key", "password", "secret"):
        result.pop(key, None)
    return result


__all__ = (
    "READ_ONLY_TOOLS",
    "authorize_tool",
    "redact_context",
    "validate_context",
)
