from __future__ import annotations

from typing import Any

from app.core.common.exception import BusiException


def validate_context(context: dict[str, Any]) -> None:
    if context.get("role") not in {"platform_super_admin", "tenant_admin"}:
        raise BusiException("无权使用自主监控分析 Agent", status_code=403)


def redact_context(context: dict[str, Any]) -> dict[str, Any]:
    result = dict(context)
    for key in ("token", "api_key", "password", "secret"):
        result.pop(key, None)
    return result
