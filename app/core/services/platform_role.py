from __future__ import annotations

from typing import Any

from app.core.common import audit as audit_context
from app.core.common.exception import BusiException
from app.core.services import audit as audit_service
from app.db import platform_role as platform_role_db
from app.db import user as user_db
from app.db.api import check_db_connected
from app.db.base import DB


@check_db_connected
async def list() -> list[dict[str, Any]]:
    return await platform_role_db.list(DB.get())


@check_db_connected
async def get_user_roles(user_id: int) -> list[dict[str, Any]]:
    if user_id <= 0:
        raise BusiException("user_id 必须大于 0")
    if await platform_role_db.user_exists(DB.get(), user_id) is False:
        raise BusiException("用户不存在", status_code=404)
    return await platform_role_db.get_user(DB.get(), user_id)


@check_db_connected
async def assign_user_roles(user_id: int, role_codes: list[str]) -> list[dict[str, Any]]:
    if user_id <= 0:
        raise BusiException("user_id 必须大于 0")
    normalized_codes = list(dict.fromkeys(code.strip() for code in role_codes if code.strip()))
    db = DB.get()
    async with db.transaction():
        user = await user_db.get(db, id=user_id)
        if user is None:
            raise BusiException("用户不存在", status_code=404)
        roles = []
        for code in normalized_codes:
            role = await platform_role_db.get(db, code=code, status="active")
            if role is None:
                raise BusiException(f"平台角色不存在或已禁用: {code}", status_code=400)
            if code == "p_super_admin":
                existing_user_ids = await platform_role_db.get_active_role_user_ids(
                    db, code
                )
                if any(existing_user_id != user_id for existing_user_id in existing_user_ids):
                    raise BusiException("平台只能有一个平台超级管理员", status_code=409)
            roles.append(role)

        old_roles = await platform_role_db.get_user(db, user_id)
        if (
            "p_super_admin" in {role["code"] for role in old_roles}
            and "p_super_admin" not in normalized_codes
        ):
            if len(await platform_role_db.get_active_role_user_ids(db, "p_super_admin")) <= 1:
                raise BusiException("平台必须保留一个平台超级管理员", status_code=409)
        await platform_role_db.delete_user_roles(db, user_id)
        actor_id = audit_context.get_context().get("actor_id")
        created_by = int(actor_id) if actor_id and actor_id.isdigit() else None
        for role in roles:
            await platform_role_db.insert_user_role(
                db,
                user_id=user_id,
                role_id=role["id"],
                created_by=created_by,
            )
        new_roles = await platform_role_db.get_user(db, user_id)
        await audit_service.record(
            db,
            action="assign_platform_roles",
            target_type="user",
            target_id=user_id,
            summary={
                "before": [role["code"] for role in old_roles],
                "after": [role["code"] for role in new_roles],
            },
        )
    return new_roles


__all__ = ("assign_user_roles", "get_user_roles", "list")
