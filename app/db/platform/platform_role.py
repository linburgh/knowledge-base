from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db import api as db_api
from app.db.models import PlatformRole, PlatformUserRole, User


async def list(db, status: str | None = "active") -> list[dict[str, Any]]:
    query = sa.select(PlatformRole).order_by(PlatformRole.c.id.asc())
    if status is not None:
        query = query.where(PlatformRole.c.status == status)
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def get(db, **kwargs: Any) -> dict[str, Any] | None:
    return await db_api.get(db, PlatformRole, **kwargs)


async def get_user(db, user_id: int) -> list[dict[str, Any]]:
    query = (
        sa.select(PlatformRole)
        .select_from(
            PlatformUserRole.join(
                PlatformRole,
                PlatformRole.c.id == PlatformUserRole.c.role_id,
            )
        )
        .where(PlatformUserRole.c.user_id == user_id)
        .order_by(PlatformRole.c.id.asc())
    )
    rows = await db.fetch_all(query)
    return [dict(row) for row in rows]


async def get_active_role_user_ids(db, role_code: str) -> list[int]:
    query = (
        sa.select(PlatformUserRole.c.user_id)
        .select_from(
            PlatformUserRole.join(
                PlatformRole,
                PlatformRole.c.id == PlatformUserRole.c.role_id,
            )
        )
        .where(
            PlatformRole.c.code == role_code,
            PlatformRole.c.status == "active",
        )
        .order_by(PlatformUserRole.c.user_id.asc())
    )
    return [int(row[0]) for row in await db.fetch_all(query)]


async def insert_user_role(db, **kwargs: Any) -> Any:
    return await db_api.insert_(db, PlatformUserRole, **kwargs)


async def delete_user_roles(db, user_id: int) -> Any:
    return await db_api.delete_(db, PlatformUserRole, user_id=user_id)


async def user_exists(db, user_id: int) -> bool:
    row = await db.fetch_one(sa.select(User.c.id).where(User.c.id == user_id).limit(1))
    return row is not None


__all__ = (
    "delete_user_roles",
    "get",
    "get_active_role_user_ids",
    "get_user",
    "insert_user_role",
    "list",
    "user_exists",
)
