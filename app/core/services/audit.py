from __future__ import annotations

from typing import Any

from app.core.common import audit as audit_context
from app.db import audit_log as audit_log_db


async def record(
    db,
    *,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    result: str = "success",
    error_message: str | None = None,
    summary: dict[str, Any] | None = None,
) -> Any:
    context = audit_context.get_context()
    return await audit_log_db.insert_(
        db,
        actor_id=context.get("actor_id") or "system",
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        request_id=context.get("request_id"),
        request_summary=audit_context.request_summary(summary),
        result=result,
        error_message=error_message,
    )


__all__ = ("record",)
