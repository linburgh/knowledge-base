from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from app.core.common import auth

AuditContext = dict[str, str | None]
_DEFAULT_CONTEXT: AuditContext = {
    "actor_id": "system",
    "request_id": None,
    "ip_address": None,
    "user_agent": None,
}
_context: ContextVar[AuditContext | None] = ContextVar("audit_context", default=None)


def set_context(**values: str | None):
    return _context.set({**get_context(), **values})


def reset_context(token) -> None:
    _context.reset(token)


def get_context() -> AuditContext:
    return dict(_context.get() or _DEFAULT_CONTEXT)


def actor_from_request(authorization: str | None) -> str:
    if authorization:
        try:
            return auth.parse_token(authorization.removeprefix("Bearer ").strip()).user_id
        except Exception:
            return "anonymous"
    return "anonymous"


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items() if key not in {
            "password", "password_hash", "token", "access_token", "api_key",
        }}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def request_summary(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    context = get_context()
    summary: dict[str, Any] = {
        "ip_address": context.get("ip_address"),
        "user_agent": context.get("user_agent"),
    }
    if extra:
        summary.update(extra)
    return _safe(summary)


__all__ = (
    "actor_from_request",
    "get_context",
    "reset_context",
    "request_summary",
    "set_context",
)
