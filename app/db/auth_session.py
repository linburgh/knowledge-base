from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db import api as db_api
from app.db.models import AuthSession


async def insert_(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, AuthSession, **kwargs)


async def get_active(db, jti: str, token_type: str) -> dict[str, Any] | None:
    session = await db_api.get(db, AuthSession, jti=jti, token_type=token_type)
    if session is None or session.get("revoked_at") is not None:
        return None
    expires_at = session.get("expires_at")
    if expires_at is not None:
        expires_at = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
        if expires_at <= datetime.now(UTC):
            return None
    return session


async def revoke(db, jti: str, *, revoked_at: datetime) -> Any:
    return await db_api.update_(db, AuthSession, {"revoked_at": revoked_at}, jti=jti)


async def revoke_all(db, user_id: int | str, *, revoked_at: datetime) -> Any:
    return await db_api.update_(
        db,
        AuthSession,
        {"revoked_at": revoked_at},
        user_id=int(user_id),
    )


__all__ = ("get_active", "insert_", "revoke", "revoke_all")
